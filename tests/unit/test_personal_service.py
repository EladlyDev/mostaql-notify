"""Unit tests for the surface-agnostic personal service (Feature 3, T014).

The service is the single source of truth both the API and the bot call, so its rules are tested
directly here without HTTP/Telegram: lazy single-record get-or-create, favorite toggle, status
validation + status_changed_at stamping, the applied-once rule, won_amount ≥ 0, hide/unhide,
append-vs-replace notes, tag normalization, and last-write-wins board moves.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from mostaql_notifier.db.models import PersonalRecord
from mostaql_notifier.personal import service as svc
from mostaql_notifier.personal.service import PersonalValidationError

PID = 1  # FK enforcement is off in the unit engine, so a bare project_id is fine here.


def _count(session) -> int:
    return session.query(PersonalRecord).count()


def test_get_or_create_is_idempotent(db_session, settings):
    a = svc.get_or_create(db_session, PID)
    b = svc.get_or_create(db_session, PID)
    assert a is b
    assert a.status == "new"  # configured default
    assert a.favorite is False and a.tags == [] and a.notes == ""
    assert _count(db_session) == 1


def test_toggle_favorite(db_session, settings):
    assert svc.toggle_favorite(db_session, PID).favorite is True
    assert svc.toggle_favorite(db_session, PID).favorite is False
    assert _count(db_session) == 1  # same record


def test_set_status_validates_and_stamps(db_session, settings):
    rec = svc.set_status(db_session, PID, "interested")
    assert rec.status == "interested"
    assert rec.status_changed_at is not None
    with pytest.raises(PersonalValidationError) as ei:
        svc.set_status(db_session, PID, "bogus")
    assert ei.value.key == "status"


def test_status_changed_at_only_on_real_change(db_session, settings):
    rec = svc.set_status(db_session, PID, "interested")
    first_stamp = rec.status_changed_at
    rec = svc.set_status(db_session, PID, "interested")  # no-op
    assert rec.status_changed_at == first_stamp


def test_applied_once(db_session, settings):
    rec = svc.set_status(db_session, PID, "applied")
    first_applied = rec.applied_at
    assert first_applied is not None
    # Leave and re-enter applied: the date must NOT move (FR-005).
    svc.set_status(db_session, PID, "interested")
    rec = svc.set_status(db_session, PID, "applied")
    assert rec.applied_at == first_applied


def test_set_applied_convenience(db_session, settings):
    rec = svc.set_applied(db_session, PID)
    assert rec.status == "applied" and rec.applied_at is not None


def test_won_amount_must_be_nonnegative(db_session, settings):
    rec = svc.set_outcome(db_session, PID, won_amount=500)
    assert rec.won_amount == Decimal("500")
    with pytest.raises(PersonalValidationError) as ei:
        svc.set_outcome(db_session, PID, won_amount=-1)
    assert ei.value.key == "won_amount"


def test_lost_reason_trimmed(db_session, settings):
    rec = svc.set_outcome(db_session, PID, lost_reason="  too expensive  ")
    assert rec.lost_reason == "too expensive"


def test_hide_unhide(db_session, settings):
    assert svc.hide(db_session, PID).hidden is True
    assert svc.unhide(db_session, PID).hidden is False


def test_set_notes_replace_and_append(db_session, settings):
    svc.set_notes(db_session, PID, "first")
    rec = svc.set_notes(db_session, PID, "second", append=True)
    assert rec.notes == "first\n\nsecond"
    rec = svc.set_notes(db_session, PID, "replaced")  # replace
    assert rec.notes == "replaced"
    # Appending blank is a harmless no-op (non-destructive).
    rec = svc.set_notes(db_session, PID, "   ", append=True)
    assert rec.notes == "replaced"


def test_tags_normalized_and_deduped(db_session, settings):
    rec = svc.set_tags(db_session, PID, ["  a ", "b", "a", "", "b"])
    assert rec.tags == ["a", "b"]
    rec = svc.add_tags(db_session, PID, ["c", "a"])
    assert rec.tags == ["a", "b", "c"]
    rec = svc.remove_tags(db_session, PID, ["b"])
    assert rec.tags == ["a", "c"]


def test_move_sets_status_position_and_applied_date(db_session, settings):
    rec = svc.move(db_session, PID, "applied", 2.5)
    assert rec.status == "applied"
    assert rec.board_position == 2.5
    assert rec.applied_at is not None


def test_move_last_write_wins(db_session, settings):
    svc.move(db_session, PID, "interested", 1.0)
    rec = svc.move(db_session, PID, "interested", 9.0)  # rapid successive moves converge
    assert rec.board_position == 9.0
    rec = svc.reorder(db_session, PID, 3.0)
    assert rec.board_position == 3.0


def test_apply_update_partial(db_session, settings):
    rec = svc.apply_update(
        db_session, PID, {"favorite": True, "status": "won", "won_amount": 1200, "tags": ["x"]}
    )
    assert rec.favorite is True
    assert rec.status == "won"
    assert rec.won_amount == Decimal("1200")
    assert rec.tags == ["x"]
    assert _count(db_session) == 1
