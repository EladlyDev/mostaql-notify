"""Unit tests for the config-driven personal status helpers (Feature 3, T013).

Covers: the default slug is the first configured entry; the reserved ``applied`` slug resolves; an
unknown key fails validation; a key removed from config still surfaces a readable label via the
fallback (never erased — constitution IV).
"""
from __future__ import annotations

import json

from mostaql_notifier.db.models import Setting
from mostaql_notifier.personal import statuses


def test_default_is_first_entry(db_session, settings):
    assert statuses.default_status(db_session) == "new"
    listed = statuses.list_statuses(db_session)
    assert [s["key"] for s in listed] == [
        "new", "interested", "applied", "in_discussion", "won", "lost", "ignored"
    ]


def test_applied_slug_resolves(db_session, settings):
    assert statuses.APPLIED_KEY == "applied"
    assert statuses.is_valid(db_session, "applied")
    assert statuses.label_for(db_session, "applied") == "تقدّمت"


def test_unknown_key_rejected(db_session, settings):
    assert not statuses.is_valid(db_session, "nonexistent")
    assert "nonexistent" not in statuses.valid_keys(db_session)


def test_removed_key_surfaces_via_fallback(db_session, settings):
    # A record may hold a status whose key was later removed from config; label_for must still
    # return *something* readable (the slug itself) rather than raising or erasing it.
    assert statuses.label_for(db_session, "retired_stage") == "retired_stage"
    assert not statuses.is_valid(db_session, "retired_stage")


def test_default_follows_config_order(db_session, settings):
    # Reorder the configured list -> the default tracks the new first entry (config over code).
    row = db_session.get(Setting, "personal_statuses")
    row.value = json.dumps(
        [{"key": "triage", "label": "فرز"}, {"key": "new", "label": "جديد"}],
        ensure_ascii=False,
    )
    db_session.commit()
    assert statuses.default_status(db_session) == "triage"


def test_malformed_config_is_defensive(db_session, settings):
    row = db_session.get(Setting, "personal_statuses")
    row.value = json.dumps("not a list")
    db_session.commit()
    assert statuses.list_statuses(db_session) == []
    assert statuses.default_status(db_session) == "new"  # last-resort fallback
