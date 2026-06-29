"""Edge coverage for POST /api/projects/{id}/personal/revert-auto-status (Feature 4, R8).

Extends ``test_personal_autostatus_revert`` with: the response DTO clearing ``auto_status_from`` /
``auto_status_at`` after a revert; a second revert being a 422 no-op (the trail is already cleared);
an existing project with NO personal record returning 422 (not 404); and auth unlocking after login.
"""
from __future__ import annotations

from datetime import datetime, timezone

from mostaql_notifier.db.models import PersonalRecord
from tests.api.conftest import make_personal_record, make_project

_REVERT = "/api/projects/{pid}/personal/revert-auto-status"


def _seed_auto_transitioned(api_env, **over) -> int:
    auto_at = datetime(2025, 3, 1, 12, 0, tzinfo=timezone.utc)
    with api_env.session() as s:
        p = make_project(s, _n=1)
        make_personal_record(
            s,
            project=p,
            status="expired_missed",
            auto_status_from="interested",
            auto_status_at=auto_at,
            **over,
        )
        s.commit()
        return p.id


def test_response_dto_clears_auto_trail_fields(api_env):
    pid = _seed_auto_transitioned(api_env)
    body = api_env.client().post(_REVERT.format(pid=pid)).json()
    assert body["status"] == "interested"
    # The trail fields are surfaced on the DTO and are null after the revert.
    assert body["auto_status_from"] is None
    assert body["auto_status_at"] is None
    assert body["status_changed_at"] is not None


def test_second_revert_is_422_no_op(api_env):
    pid = _seed_auto_transitioned(api_env)
    client = api_env.client()
    assert client.post(_REVERT.format(pid=pid)).status_code == 200

    # The trail is now cleared — a second revert has nothing to undo.
    resp = client.post(_REVERT.format(pid=pid))
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Validation failed"
    with api_env.session() as s:
        assert s.get(PersonalRecord, pid).status == "interested"


def test_existing_project_without_record_is_422_not_404(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)  # project exists, but no personal record
        s.commit()
        pid = p.id

    resp = api_env.client().post(_REVERT.format(pid=pid))
    assert resp.status_code == 422  # the project is found (so not 404); there is nothing to revert


def test_revert_unlocks_after_login_when_auth_enabled(api_env):
    pid = _seed_auto_transitioned(api_env)
    client = api_env.client(auth_enabled=True, password="pw")
    assert client.post(_REVERT.format(pid=pid)).status_code == 401
    assert client.post("/api/auth/login", json={"password": "pw"}).status_code == 200
    assert client.post(_REVERT.format(pid=pid)).status_code == 200
