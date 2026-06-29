"""Exhaustive edge-case unit tests for the config-driven status helpers (Feature 3).

Complements ``test_personal_statuses.py`` by exercising the defensive ``_load`` paths: a non-list
config, an empty list, malformed entries (a non-dict and a dict missing ``"key"``) that must be
skipped, the ``label`` default-to-key behaviour, list-order preservation, and the removed-key
readable-fallback for ``label_for``.
"""
from __future__ import annotations

import json

from mostaql_notifier.db.models import Setting
from mostaql_notifier.personal import statuses


def _set_statuses(session, value) -> None:
    """Overwrite the ``personal_statuses`` settings row (JSON) so a fresh SettingsStore reads it."""
    row = session.get(Setting, "personal_statuses")
    row.value = json.dumps(value, ensure_ascii=False)
    session.commit()


# --- defaults / ordering with the seeded config -------------------------------------------------

def test_default_is_first_entry_and_order_preserved(db_session, settings):
    assert statuses.default_status(db_session) == "new"
    assert [s["key"] for s in statuses.list_statuses(db_session)] == [
        "new", "interested", "applied", "in_discussion", "won", "lost", "expired_missed", "ignored"
    ]


def test_valid_keys_and_is_valid(db_session, settings):
    keys = statuses.valid_keys(db_session)
    assert keys == {
        "new", "interested", "applied", "in_discussion", "won", "lost", "expired_missed", "ignored"
    }
    assert statuses.is_valid(db_session, "applied") is True
    assert statuses.is_valid(db_session, "nope") is False


def test_label_for_present_key_returns_label(db_session, settings):
    assert statuses.label_for(db_session, "won") == "ربح"


def test_label_for_removed_key_returns_slug(db_session, settings):
    # A record may still hold a key that was dropped from config: stay readable, never raise.
    assert statuses.label_for(db_session, "retired_stage") == "retired_stage"
    assert statuses.is_valid(db_session, "retired_stage") is False


# --- defensive _load paths ----------------------------------------------------------------------

def test_non_list_config_falls_back(db_session, settings):
    _set_statuses(db_session, {"not": "a list"})  # a dict, not a list
    assert statuses.list_statuses(db_session) == []
    assert statuses.default_status(db_session) == "new"
    assert statuses.valid_keys(db_session) == set()
    assert statuses.is_valid(db_session, "new") is False


def test_empty_config_falls_back(db_session, settings):
    _set_statuses(db_session, [])
    assert statuses.list_statuses(db_session) == []
    assert statuses.default_status(db_session) == "new"  # last-resort fallback
    assert statuses.valid_keys(db_session) == set()


def test_malformed_entries_are_skipped(db_session, settings):
    # "garbage" is not a dict; {"nokey": 1} is a dict without "key" -> both skipped (branch 36->35).
    _set_statuses(
        db_session,
        [
            {"key": "new", "label": "جديد"},
            "garbage",
            {"nokey": 1},
            {"key": "applied", "label": "تقدّمت"},
        ],
    )
    listed = statuses.list_statuses(db_session)
    assert listed == [
        {"key": "new", "label": "جديد"},
        {"key": "applied", "label": "تقدّمت"},
    ]
    assert statuses.valid_keys(db_session) == {"new", "applied"}


def test_label_defaults_to_key_when_missing(db_session, settings):
    _set_statuses(db_session, [{"key": "draft"}])  # no "label"
    assert statuses.list_statuses(db_session) == [{"key": "draft", "label": "draft"}]
    assert statuses.label_for(db_session, "draft") == "draft"
    assert statuses.default_status(db_session) == "draft"


def test_default_tracks_reordered_first_entry(db_session, settings):
    _set_statuses(
        db_session,
        [{"key": "triage", "label": "فرز"}, {"key": "new", "label": "جديد"}],
    )
    assert statuses.default_status(db_session) == "triage"
    assert [s["key"] for s in statuses.list_statuses(db_session)] == ["triage", "new"]
