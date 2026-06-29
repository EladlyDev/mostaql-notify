"""The surface-agnostic personal-layer service (Feature 3, research §3).

Every personal mutation lives here; the FastAPI routers **and** the inbound Telegram bot call these
functions and neither reimplements the rules. Centralised here: lazy get-or-create, the
**applied-once** rule (stamp ``applied_at`` on the first entry into ``applied``, never overwrite —
FR-005), stamping ``status_changed_at`` on a real status change (FR-008), ``won_amount`` ≥ 0
validation, append-only notes from the bot, and **last-write-wins** board moves (FR-023).

All functions are synchronous and take an open SQLAlchemy ``Session``; the caller owns the
transaction boundary (the API's ``get_db`` commits per request; the bot commits per handler). They
``flush`` so a freshly-created record gets its defaults, but do not ``commit``.
"""
from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from ..db.models import PersonalRecord
from ..db.types import utcnow
from . import statuses


class PersonalValidationError(ValueError):
    """A field-level validation failure the API maps to 422 and the bot reports inline."""

    def __init__(self, key: str, message: str):
        self.key = key
        self.message = message
        super().__init__(message)


def get_or_create(session: Session, project_id: int) -> PersonalRecord:
    """Fetch the project's personal record, creating it (status = configured default) on first
    touch. Idempotent — exactly one record per project (PK = project_id)."""
    rec = session.get(PersonalRecord, project_id)
    if rec is None:
        rec = PersonalRecord(project_id=project_id, status=statuses.default_status(session))
        session.add(rec)
        session.flush()
    return rec


def toggle_favorite(session: Session, project_id: int) -> PersonalRecord:
    """Flip the favorite flag (Telegram ⭐ button + feed one-click parity)."""
    rec = get_or_create(session, project_id)
    rec.favorite = not rec.favorite
    return rec


def set_favorite(session: Session, project_id: int, value: bool) -> PersonalRecord:
    rec = get_or_create(session, project_id)
    rec.favorite = bool(value)
    return rec


def set_status(session: Session, project_id: int, key: str) -> PersonalRecord:
    """Set the personal status. Validates against the configured set (422 on unknown), stamps
    ``status_changed_at`` on a real change, and applies the **applied-once** rule when entering
    ``applied``."""
    if not statuses.is_valid(session, key):
        raise PersonalValidationError("status", f"Unknown status: {key!r}")
    rec = get_or_create(session, project_id)
    if key != rec.status:
        rec.status = key
        rec.status_changed_at = utcnow()
    # Applied-once: stamp today on first entry into 'applied'; never overwrite (FR-005).
    if key == statuses.APPLIED_KEY and rec.applied_at is None:
        rec.applied_at = utcnow()
    return rec


def set_applied(session: Session, project_id: int) -> PersonalRecord:
    """Convenience for the Telegram ✅ button — set status to ``applied`` (records the date once)."""
    return set_status(session, project_id, statuses.APPLIED_KEY)


def revert_auto_status(session: Session, project_id: int) -> PersonalRecord:
    """Undo the optional auto personal-status transition (Feature 4, R8 / data-model).

    Restores the status the record held immediately before the automated change
    (``auto_status_from``), re-stamps ``status_changed_at``, then clears the auto-trail
    (``auto_status_from`` / ``auto_status_at``). Owner data — favorite/tags/notes/applied_at/
    won_amount/lost_reason/attachments — is never touched. Raises
    :class:`PersonalValidationError` (no row, or nothing to revert) when there is no recorded
    auto-change to undo."""
    rec = session.get(PersonalRecord, project_id)
    if rec is None or rec.auto_status_from is None:
        raise PersonalValidationError("auto_status", "لا يوجد تغيير تلقائي للتراجع عنه")
    rec.status = rec.auto_status_from
    rec.status_changed_at = utcnow()
    rec.auto_status_from = None
    rec.auto_status_at = None
    session.flush()
    return rec


def _coerce_amount(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise PersonalValidationError("won_amount", "won_amount must be a number") from None


def set_outcome(
    session: Session,
    project_id: int,
    *,
    won_amount: object | None = None,
    lost_reason: str | None = None,
) -> PersonalRecord:
    """Record the outcome fields. ``won_amount`` must be ≥ 0; ``lost_reason`` is trimmed."""
    rec = get_or_create(session, project_id)
    if won_amount is not None:
        amount = _coerce_amount(won_amount)
        # Reject NaN/±inf BEFORE the ``< 0`` compare (``Decimal('NaN') < 0`` raises): a non-finite
        # amount is meaningless money and would serialize as invalid JSON (Infinity/NaN).
        if not amount.is_finite():
            raise PersonalValidationError("won_amount", "won_amount must be a finite number")
        if amount < 0:
            raise PersonalValidationError("won_amount", "won_amount must be ≥ 0")
        rec.won_amount = amount
    if lost_reason is not None:
        rec.lost_reason = lost_reason.strip() or None
    return rec


def _normalize_tags(tags: object) -> list[str]:
    """Trim, drop empties, de-duplicate (preserve first-seen order)."""
    if not isinstance(tags, (list, tuple)):
        raise PersonalValidationError("tags", "tags must be a list of strings")
    seen: list[str] = []
    for t in tags:
        s = str(t).strip()
        if s and s not in seen:
            seen.append(s)
    return seen


def set_tags(session: Session, project_id: int, tags: list[str]) -> PersonalRecord:
    rec = get_or_create(session, project_id)
    rec.tags = _normalize_tags(tags)
    return rec


def add_tags(session: Session, project_id: int, tags: list[str]) -> PersonalRecord:
    rec = get_or_create(session, project_id)
    rec.tags = _normalize_tags(list(rec.tags or []) + list(tags))
    return rec


def remove_tags(session: Session, project_id: int, tags: list[str]) -> PersonalRecord:
    rec = get_or_create(session, project_id)
    drop = {str(t).strip() for t in tags}
    rec.tags = [t for t in (rec.tags or []) if t not in drop]
    return rec


def hide(session: Session, project_id: int) -> PersonalRecord:
    """Hide/dismiss — drops the project from the active feed + board; data is untouched (FR-007)."""
    rec = get_or_create(session, project_id)
    rec.hidden = True
    return rec


def unhide(session: Session, project_id: int) -> PersonalRecord:
    rec = get_or_create(session, project_id)
    rec.hidden = False
    return rec


def set_notes(session: Session, project_id: int, notes: str, *, append: bool = False) -> PersonalRecord:
    """Replace (dashboard editor) or append (Telegram add-note) the markdown notes. Append never
    overwrites — non-destructive (constitution IV)."""
    rec = get_or_create(session, project_id)
    if append:
        addition = (notes or "").strip()
        if addition:
            rec.notes = f"{rec.notes}\n\n{addition}" if rec.notes else addition
    else:
        rec.notes = notes or ""
    return rec


def set_applied_at(session: Session, project_id: int, applied_at: object | None) -> PersonalRecord:
    """Owner-initiated set/correct of the applied date (distinct from the automation rule)."""
    rec = get_or_create(session, project_id)
    rec.applied_at = applied_at
    return rec


def _finite_position(position: object) -> float:
    """Coerce a board position to a finite float; reject NaN/±inf (would serialize as invalid JSON
    and break ``GET /api/board`` for every card)."""
    try:
        pos = float(position)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise PersonalValidationError("position", "position must be a number") from None
    if not math.isfinite(pos):
        raise PersonalValidationError("position", "position must be a finite number")
    return pos


def move(
    session: Session, project_id: int, to_status: str, position: float
) -> PersonalRecord:
    """Board move/reorder — set status (applied-once rule when →applied) and ``board_position``.
    Last-write-wins: a bare assignment, so rapid successive moves converge (FR-023). The position is
    validated first so an invalid move never mutates the status."""
    pos = _finite_position(position)
    set_status(session, project_id, to_status)
    rec = get_or_create(session, project_id)
    rec.board_position = pos
    return rec


def reorder(session: Session, project_id: int, position: float) -> PersonalRecord:
    """Reorder within the current column (priority) without changing status."""
    pos = _finite_position(position)
    rec = get_or_create(session, project_id)
    rec.board_position = pos
    return rec


# Fields a partial PATCH may carry → applied in a deterministic order through the rules above.
def apply_update(session: Session, project_id: int, update: dict) -> PersonalRecord:
    """Apply a partial update (the API ``PATCH`` body) through the per-field rules. Unknown keys are
    ignored; validation errors raise :class:`PersonalValidationError`."""
    rec = get_or_create(session, project_id)
    if "favorite" in update:
        rec.favorite = bool(update["favorite"])
    if "status" in update and update["status"] is not None:
        set_status(session, project_id, update["status"])
    if "tags" in update:
        set_tags(session, project_id, update["tags"])
    if update.get("won_amount") is not None or update.get("lost_reason") is not None:
        set_outcome(
            session,
            project_id,
            won_amount=update.get("won_amount"),
            lost_reason=update.get("lost_reason"),
        )
    if "applied_at" in update:
        rec.applied_at = update["applied_at"]
    if "notes" in update and update["notes"] is not None:
        set_notes(session, project_id, update["notes"])
    if "hidden" in update and update["hidden"] is not None:
        rec.hidden = bool(update["hidden"])
    if "reminder_at" in update:
        rec.reminder_at = update["reminder_at"]
    return rec
