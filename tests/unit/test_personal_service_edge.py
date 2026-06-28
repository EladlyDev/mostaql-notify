"""Exhaustive edge-case unit tests for the personal service (Feature 3).

Complements ``test_personal_service.py`` by driving every branch and corner of
``personal/service.py`` directly (no HTTP/Telegram): exact-value favorite setters, the applied-once
rule across leave/re-enter, Decimal precision + the won_amount guards, tag normalization + the
non-list guard, append-vs-replace notes corner cases, owner-set/clear of ``applied_at``,
last-write-wins board moves, the move/invalid-status no-record guarantee, and every ``apply_update``
field path.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from mostaql_notifier.db.models import EvalStatus, PersonalRecord, Project, ProjectStatus
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.personal import service, statuses


def _make_project(session, mostaql_id: str = "p1") -> int:
    """Insert a minimal Project row and return its id (so the 1:1 personal record has a real FK)."""
    p = Project(
        mostaql_id=mostaql_id,
        scraped_at=utcnow(),
        site_status=ProjectStatus.unknown,
        eval_status=EvalStatus.pending,
        raw={},
    )
    session.add(p)
    session.flush()
    return p.id


def _count(session) -> int:
    return session.query(PersonalRecord).count()


# --- get_or_create / favorite -------------------------------------------------------------------

def test_get_or_create_idempotent_and_default(db_session, settings):
    pid = _make_project(db_session)
    a = service.get_or_create(db_session, pid)
    b = service.get_or_create(db_session, pid)
    assert a is b  # exactly one record per project
    assert a.status == statuses.default_status(db_session) == "new"
    assert a.favorite is False
    assert a.tags == []
    assert a.notes == ""
    assert a.hidden is False
    assert a.applied_at is None
    assert _count(db_session) == 1


def test_toggle_favorite_flips(db_session, settings):
    pid = _make_project(db_session)
    assert service.toggle_favorite(db_session, pid).favorite is True
    assert service.toggle_favorite(db_session, pid).favorite is False
    assert _count(db_session) == 1


def test_set_favorite_exact_and_idempotent(db_session, settings):
    pid = _make_project(db_session)
    assert service.set_favorite(db_session, pid, True).favorite is True
    assert service.set_favorite(db_session, pid, True).favorite is True  # idempotent
    assert service.set_favorite(db_session, pid, False).favorite is False
    assert service.set_favorite(db_session, pid, False).favorite is False
    assert _count(db_session) == 1


# --- status + status_changed_at + applied-once --------------------------------------------------

def test_set_status_valid_stamps_changed_at(db_session, settings):
    pid = _make_project(db_session)
    rec = service.set_status(db_session, pid, "interested")
    assert rec.status == "interested"
    assert rec.status_changed_at is not None


def test_set_status_same_status_does_not_restamp(db_session, settings):
    pid = _make_project(db_session)
    rec = service.set_status(db_session, pid, "interested")
    first = rec.status_changed_at
    rec = service.set_status(db_session, pid, "interested")  # no real change
    assert rec.status_changed_at == first


def test_set_status_invalid_raises(db_session, settings):
    pid = _make_project(db_session)
    with pytest.raises(service.PersonalValidationError) as ei:
        service.set_status(db_session, pid, "does-not-exist")
    assert ei.value.key == "status"


def test_applied_once_stamps_then_never_overwrites(db_session, settings):
    pid = _make_project(db_session)
    rec = service.set_status(db_session, pid, "applied")
    original = rec.applied_at
    assert original is not None
    # Re-enter 'applied' directly: must not overwrite (FR-005).
    service.set_status(db_session, pid, "applied")
    assert rec.applied_at == original
    # Move away and back: the original date survives.
    service.set_status(db_session, pid, "interested")
    service.set_status(db_session, pid, "applied")
    assert rec.applied_at == original


def test_set_applied_convenience(db_session, settings):
    pid = _make_project(db_session)
    rec = service.set_applied(db_session, pid)
    assert rec.status == statuses.APPLIED_KEY == "applied"
    assert rec.applied_at is not None


# --- outcome: won_amount + lost_reason ----------------------------------------------------------

def test_won_amount_decimal_precision_kept_exactly(db_session, settings):
    pid = _make_project(db_session)
    rec = service.set_outcome(db_session, pid, won_amount="250.50")
    assert rec.won_amount == Decimal("250.50")
    assert str(rec.won_amount) == "250.50"  # trailing zero / exponent preserved


def test_won_amount_zero_allowed(db_session, settings):
    pid = _make_project(db_session)
    rec = service.set_outcome(db_session, pid, won_amount=0)
    assert rec.won_amount == Decimal("0")


def test_won_amount_negative_raises(db_session, settings):
    pid = _make_project(db_session)
    with pytest.raises(service.PersonalValidationError) as ei:
        service.set_outcome(db_session, pid, won_amount=-0.01)
    assert ei.value.key == "won_amount"


def test_won_amount_non_numeric_raises_service_level(db_session, settings):
    pid = _make_project(db_session)
    with pytest.raises(service.PersonalValidationError) as ei:
        service.set_outcome(db_session, pid, won_amount="abc")
    assert ei.value.key == "won_amount"
    assert ei.value.message == "won_amount must be a number"


def test_coerce_amount_rejects_non_numeric_object(db_session, settings):
    with pytest.raises(service.PersonalValidationError) as ei:
        service._coerce_amount(object())
    assert ei.value.key == "won_amount"


def test_lost_reason_trimmed(db_session, settings):
    pid = _make_project(db_session)
    rec = service.set_outcome(db_session, pid, lost_reason="  too pricey  ")
    assert rec.lost_reason == "too pricey"


def test_lost_reason_whitespace_only_becomes_none(db_session, settings):
    pid = _make_project(db_session)
    rec = service.set_outcome(db_session, pid, lost_reason="    ")
    assert rec.lost_reason is None


# --- tags ---------------------------------------------------------------------------------------

def test_set_tags_trim_drop_empties_dedup_first_seen_order(db_session, settings):
    pid = _make_project(db_session)
    rec = service.set_tags(db_session, pid, ["  b ", "a", "b", "", "   ", "a", "c"])
    assert rec.tags == ["b", "a", "c"]


def test_set_tags_non_list_raises(db_session, settings):
    pid = _make_project(db_session)
    with pytest.raises(service.PersonalValidationError) as ei:
        service.set_tags(db_session, pid, "notalist")
    assert ei.value.key == "tags"


def test_normalize_tags_rejects_non_list(db_session, settings):
    with pytest.raises(service.PersonalValidationError) as ei:
        service._normalize_tags(123)
    assert ei.value.key == "tags"


def test_add_tags_merges_and_dedups(db_session, settings):
    pid = _make_project(db_session)
    service.set_tags(db_session, pid, ["a", "b"])
    rec = service.add_tags(db_session, pid, ["  b ", "c", "a"])
    assert rec.tags == ["a", "b", "c"]


def test_remove_tags_drops_trimmed_matches(db_session, settings):
    pid = _make_project(db_session)
    service.set_tags(db_session, pid, ["a", "b", "c"])
    rec = service.remove_tags(db_session, pid, ["  b "])  # trimmed match removes "b"
    assert rec.tags == ["a", "c"]


def test_remove_tags_from_empty_is_noop(db_session, settings):
    pid = _make_project(db_session)
    rec = service.remove_tags(db_session, pid, ["x"])
    assert rec.tags == []


# --- hide / unhide ------------------------------------------------------------------------------

def test_hide_then_unhide(db_session, settings):
    pid = _make_project(db_session)
    assert service.hide(db_session, pid).hidden is True
    assert service.unhide(db_session, pid).hidden is False


# --- notes: replace vs append -------------------------------------------------------------------

def test_set_notes_replace(db_session, settings):
    pid = _make_project(db_session)
    rec = service.set_notes(db_session, pid, "hello")
    assert rec.notes == "hello"


def test_set_notes_replace_none_becomes_empty(db_session, settings):
    pid = _make_project(db_session)
    service.set_notes(db_session, pid, "something")
    rec = service.set_notes(db_session, pid, None)
    assert rec.notes == ""


def test_set_notes_append_to_empty_seeds_value(db_session, settings):
    pid = _make_project(db_session)
    rec = service.set_notes(db_session, pid, "first", append=True)
    assert rec.notes == "first"  # no leading blank lines on an empty record


def test_set_notes_append_to_existing_inserts_blank_line(db_session, settings):
    pid = _make_project(db_session)
    service.set_notes(db_session, pid, "a")
    rec = service.set_notes(db_session, pid, "b", append=True)
    assert rec.notes == "a\n\nb"


def test_set_notes_append_whitespace_only_is_noop(db_session, settings):
    pid = _make_project(db_session)
    service.set_notes(db_session, pid, "kept")
    rec = service.set_notes(db_session, pid, "   ", append=True)
    assert rec.notes == "kept"


# --- set_applied_at -----------------------------------------------------------------------------

def test_set_applied_at_set_then_clear(db_session, settings):
    pid = _make_project(db_session)
    when = utcnow()
    rec = service.set_applied_at(db_session, pid, when)
    assert rec.applied_at == when
    rec = service.set_applied_at(db_session, pid, None)
    assert rec.applied_at is None


# --- board: move / reorder ----------------------------------------------------------------------

def test_move_sets_status_position_and_applies_once(db_session, settings):
    pid = _make_project(db_session)
    rec = service.move(db_session, pid, "applied", 2.5)
    assert rec.status == "applied"
    assert rec.board_position == 2.5
    assert rec.applied_at is not None


def test_move_last_write_wins(db_session, settings):
    pid = _make_project(db_session)
    service.move(db_session, pid, "interested", 1.0)
    rec = service.move(db_session, pid, "interested", 9.0)  # rapid moves converge
    assert rec.board_position == 9.0


def test_move_invalid_status_raises_and_creates_no_record(db_session, settings):
    pid = _make_project(db_session)
    with pytest.raises(service.PersonalValidationError) as ei:
        service.move(db_session, pid, "bogus", 1.0)
    assert ei.value.key == "status"
    # The validation fires before any get_or_create, so a fresh project gets no record.
    assert db_session.get(PersonalRecord, pid) is None


def test_reorder_changes_position_only(db_session, settings):
    pid = _make_project(db_session)
    service.set_status(db_session, pid, "interested")
    rec = service.reorder(db_session, pid, 4.5)
    assert rec.board_position == 4.5
    assert rec.status == "interested"  # status untouched


# --- apply_update (partial PATCH body) ----------------------------------------------------------

def test_apply_update_all_field_paths(db_session, settings):
    pid = _make_project(db_session)
    when = utcnow()
    rec = service.apply_update(
        db_session,
        pid,
        {
            "favorite": True,
            "status": "interested",
            "tags": ["  a ", "a", "b"],
            "won_amount": 0,
            "lost_reason": "  n/a  ",
            "applied_at": when,
            "notes": "hello",
            "hidden": True,
            "reminder_at": when,
        },
    )
    assert rec.favorite is True
    assert rec.status == "interested"
    assert rec.tags == ["a", "b"]
    assert rec.won_amount == Decimal("0")
    assert rec.lost_reason == "n/a"
    assert rec.applied_at == when  # explicit applied_at applied (line 205)
    assert rec.notes == "hello"  # notes path (line 207)
    assert rec.hidden is True
    assert rec.reminder_at == when  # reminder_at path (line 211)


def test_apply_update_partial_only_touches_provided_keys(db_session, settings):
    pid = _make_project(db_session)
    service.set_status(db_session, pid, "won")
    service.set_tags(db_session, pid, ["keep"])
    service.set_notes(db_session, pid, "diary")
    rec = service.apply_update(db_session, pid, {"favorite": True})
    assert rec.favorite is True
    assert rec.status == "won"  # untouched
    assert rec.tags == ["keep"]  # untouched
    assert rec.notes == "diary"  # untouched
    assert _count(db_session) == 1


def test_apply_update_invalid_status_raises(db_session, settings):
    pid = _make_project(db_session)
    with pytest.raises(service.PersonalValidationError) as ei:
        service.apply_update(db_session, pid, {"status": "bogus"})
    assert ei.value.key == "status"


def test_apply_update_won_amount_zero_via_patch(db_session, settings):
    pid = _make_project(db_session)
    rec = service.apply_update(db_session, pid, {"won_amount": 0})
    assert rec.won_amount == Decimal("0")
