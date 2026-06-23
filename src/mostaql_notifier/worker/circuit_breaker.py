"""Block / structure-change detection and the loop circuit breaker (research §5, US2).

Fail-closed: a block is NEVER treated as "no new projects". On a block/challenge/structure-change we
alert, do not advance seen-state, and do not mark the poll successful.
"""
from __future__ import annotations

import enum
from datetime import timedelta

from ..config.settings_store import app_state_get, app_state_set
from ..db.types import utcnow
from ..scraper.fetcher import FetchResult


class Classification(str, enum.Enum):
    ok = "ok"
    blocked = "blocked"            # 403 / 429
    transient = "transient"        # 5xx / transport error -> per-request backoff
    challenge = "challenge"        # CAPTCHA / Cloudflare marker or suspiciously small body
    structure_change = "structure_change"  # 200, no markers, but 0 parsed rows on a non-empty page


def classify_response(result: FetchResult, settings) -> Classification:
    if result.status in (403, 429):
        return Classification.blocked
    if result.status == 0 or 500 <= result.status < 600:
        return Classification.transient
    if result.status == 200:
        body_lower = result.body.lower()
        markers = [m.lower() for m in settings.get_json("challenge_markers")]
        if any(m in body_lower for m in markers):
            return Classification.challenge
        if result.body_bytes < settings.get_int("block_body_max_bytes"):
            return Classification.challenge
        return Classification.ok
    return Classification.transient


def is_clearly_nonempty(result: FetchResult, settings) -> bool:
    """True when a listing page should contain rows (so 0 parsed rows ⇒ structure change)."""
    if result.body_bytes < settings.get_int("nonempty_body_min_bytes"):
        return False
    body = result.body
    shell = settings.get_json("listing_shell_markers")
    empty = settings.get_json("empty_state_markers")
    if any(e in body for e in empty):
        return False
    return any(s in body for s in shell)


class CircuitBreaker:
    """Persisted in app_state so a pause survives restarts. Alerts only on state transitions."""

    def __init__(self, session):
        self.session = session

    def _get(self, key, default=None):
        return app_state_get(self.session, key, default)

    def _set(self, key, value):
        app_state_set(self.session, key, str(value))

    @property
    def consecutive_failures(self) -> int:
        return int(self._get("cb_consecutive_failures", "0") or "0")

    @property
    def trip_count(self) -> int:
        return int(self._get("cb_trip_count", "0") or "0")

    def is_paused(self) -> bool:
        resume = self._get("cb_resume_at")
        if not resume:
            return False
        return utcnow() < _parse_iso(resume)

    def resume_at(self):
        resume = self._get("cb_resume_at")
        return _parse_iso(resume) if resume else None

    def record_success(self) -> bool:
        """Returns True if this is a recovery transition (was paused/failing)."""
        # Use truthiness (matching is_paused's ``if not resume``): a cleared pause is stored as ""
        # which is NOT None, so an ``is not None`` test would re-report a transition every clean
        # cycle and double-alert. Constitution VI: alert only on real transitions.
        was_failing = self.consecutive_failures > 0 or bool(self._get("cb_resume_at"))
        self._set("cb_consecutive_failures", 0)
        if self._get("cb_resume_at") is not None:
            app_state_set(self.session, "cb_resume_at", "")
        return was_failing

    def record_failure(self, *, hard: bool, settings) -> bool:
        """Record a failed cycle. ``hard`` (block/challenge) trips immediately.

        Returns True when this transitions INTO a paused state (so the caller alerts once).
        """
        fails = self.consecutive_failures + 1
        self._set("cb_consecutive_failures", fails)
        already_paused = self.is_paused()
        should_trip = hard or fails >= 3
        if should_trip and not already_paused:
            trips = self.trip_count + 1
            base = settings.get_int("cb_cooldown_minutes")
            factor = settings.get_int("cb_cooldown_factor")
            cap = settings.get_int("cb_cooldown_max_minutes")
            minutes = min(base * (factor ** (trips - 1)), cap)
            self._set("cb_trip_count", trips)
            self._set("cb_resume_at", (utcnow() + timedelta(minutes=minutes)).isoformat())
            return True
        return False


def _parse_iso(value: str):
    from datetime import datetime, timezone

    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
