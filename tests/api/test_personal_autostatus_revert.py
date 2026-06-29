"""API coverage for the reversible auto personal-status revert (Feature 4, US4 / R8).

The re-check loop can — only when ``auto_status_personal_enabled`` is on — auto-transition an
``interested`` record to ``expired_missed`` when its project closes, recording the prior status in
``auto_status_from`` and the time in ``auto_status_at``. This suite exercises the **revert**: the
owner-gated POST restores the prior status, clears the auto-trail, re-stamps ``status_changed_at``,
and never touches notes/tags/favorite/applied data. Mirrors the fixtures/factories in
``tests/api/conftest.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from mostaql_notifier.db.models import PersonalRecord
from tests.api.conftest import make_personal_record, make_project

_REVERT = "/api/projects/{pid}/personal/revert-auto-status"


def _seed_auto_transitioned(api_env, **over) -> int:
    """Seed a project + a personal record the loop auto-moved interested→expired_missed."""
    auto_at = datetime(2025, 2, 1, 9, 0, tzinfo=timezone.utc)
    with api_env.session() as s:
        p = make_project(s, _n=1)
        make_personal_record(
            s,
            project=p,
            status="expired_missed",
            auto_status_from="interested",
            auto_status_at=auto_at,
            tags=["عاجل", "تصميم"],
            notes="ملاحظة مهمة",
            favorite=True,
            **over,
        )
        s.commit()
        return p.id


def test_revert_restores_prior_status_and_clears_auto_trail(api_env):
    pid = _seed_auto_transitioned(api_env)
    client = api_env.client(auth_enabled=False)

    resp = client.post(_REVERT.format(pid=pid))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "interested"
    assert body["status_label"] == "مهتم"  # resolved from config, not the raw slug
    assert body["status_changed_at"] is not None  # re-stamped on the revert
    # Owner data is never touched by the revert (constitution IV).
    assert body["favorite"] is True
    assert body["tags"] == ["عاجل", "تصميم"]
    assert body["notes"] == "ملاحظة مهمة"

    # The auto-trail (not part of the response DTO) is cleared in the DB.
    with api_env.session() as s:
        rec = s.get(PersonalRecord, pid)
        assert rec.status == "interested"
        assert rec.auto_status_from is None
        assert rec.auto_status_at is None
        assert rec.status_changed_at is not None


def test_revert_without_a_recorded_auto_change_is_422(api_env):
    # A record with no auto-trail has nothing to revert.
    with api_env.session() as s:
        p = make_project(s, _n=1)
        make_personal_record(s, project=p, status="interested")
        s.commit()
        pid = p.id

    client = api_env.client(auth_enabled=False)
    resp = client.post(_REVERT.format(pid=pid))
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "Validation failed"
    assert body["errors"][0]["message"]  # a human-readable Arabic message is present

    # The status is left exactly as it was — the failed revert mutated nothing.
    with api_env.session() as s:
        assert s.get(PersonalRecord, pid).status == "interested"


def test_revert_missing_project_is_404(api_env):
    client = api_env.client(auth_enabled=False)
    assert client.post(_REVERT.format(pid=987654)).status_code == 404


def test_revert_requires_auth_when_enabled(api_env):
    pid = _seed_auto_transitioned(api_env)
    client = api_env.client(auth_enabled=True, password="pw")
    assert client.post(_REVERT.format(pid=pid)).status_code == 401
