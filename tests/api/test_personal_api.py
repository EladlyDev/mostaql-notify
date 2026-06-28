"""T015 — personal record API: defaults, create-on-first-touch, the per-field rules, auth."""
from __future__ import annotations

from sqlalchemy import func, select

from mostaql_notifier.db.models import PersonalRecord
from tests.api.conftest import make_project


def _count_records(api_env) -> int:
    with api_env.session() as s:
        return s.scalar(select(func.count()).select_from(PersonalRecord)) or 0


def test_get_returns_defaults_without_creating_a_row(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        s.commit()
        pid = p.id

    client = api_env.client(auth_enabled=False)
    data = client.get(f"/api/projects/{pid}/personal").json()
    assert data["project_id"] == pid
    assert data["favorite"] is False
    assert data["status"] == "new"  # the configured default (first entry)
    assert data["status_label"] == "جديد"
    assert data["tags"] == []
    assert data["notes"] == ""
    assert data["board_position"] == 0.0
    assert data["hidden"] is False
    assert data["applied_at"] is None
    assert data["won_amount"] is None
    assert data["lost_reason"] is None
    # GET must not lazily create a row.
    assert _count_records(api_env) == 0


def test_get_404_when_project_missing(api_env):
    client = api_env.client(auth_enabled=False)
    assert client.get("/api/projects/999999/personal").status_code == 404


def test_patch_creates_on_first_touch_and_sets_fields(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        s.commit()
        pid = p.id

    client = api_env.client(auth_enabled=False)
    resp = client.patch(
        f"/api/projects/{pid}/personal",
        json={
            "favorite": True,
            "status": "applied",
            "tags": ["python", "django"],
            "won_amount": 250,
            "lost_reason": "client ghosted",
            "hidden": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["favorite"] is True
    assert data["status"] == "applied"
    assert data["status_label"] == "تقدّمت"
    assert data["tags"] == ["python", "django"]
    assert data["applied_at"] is not None  # stamped by the applied-once rule
    assert data["won_amount"] == 250.0
    assert data["lost_reason"] == "client ghosted"
    assert data["hidden"] is True
    # Exactly one row created (PK = project_id => 1:1).
    assert _count_records(api_env) == 1


def test_patch_unknown_status_returns_422(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        s.commit()
        pid = p.id

    client = api_env.client(auth_enabled=False)
    resp = client.patch(f"/api/projects/{pid}/personal", json={"status": "bogus"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"]
    assert body["errors"][0]["key"] == "status"


def test_patch_negative_won_amount_returns_422(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        s.commit()
        pid = p.id

    client = api_env.client(auth_enabled=False)
    resp = client.patch(f"/api/projects/{pid}/personal", json={"won_amount": -5})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["key"] == "won_amount"


def test_patch_404_when_project_missing(api_env):
    client = api_env.client(auth_enabled=False)
    assert client.patch("/api/projects/999999/personal", json={"favorite": True}).status_code == 404


def test_applied_once_does_not_move_applied_at(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        s.commit()
        pid = p.id

    client = api_env.client(auth_enabled=False)
    first = client.patch(f"/api/projects/{pid}/personal", json={"status": "applied"}).json()
    applied_at = first["applied_at"]
    assert applied_at is not None

    # Move off applied, then back — the second entry must NOT overwrite the stamp (FR-005).
    client.patch(f"/api/projects/{pid}/personal", json={"status": "interested"})
    second = client.patch(f"/api/projects/{pid}/personal", json={"status": "applied"}).json()
    assert second["applied_at"] == applied_at


def test_favorite_endpoint_flips_state(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        s.commit()
        pid = p.id

    client = api_env.client(auth_enabled=False)
    assert client.post(f"/api/projects/{pid}/personal/favorite").json()["favorite"] is True
    assert client.post(f"/api/projects/{pid}/personal/favorite").json()["favorite"] is False


def test_unauthenticated_returns_401(api_env):
    # Auth-enabled client, no login: the include-time gate rejects before the route runs.
    client = api_env.client(auth_enabled=True, password="pw")
    assert client.get("/api/projects/1/personal").status_code == 401
    assert client.patch("/api/projects/1/personal", json={"favorite": True}).status_code == 401
    assert client.post("/api/projects/1/personal/favorite").status_code == 401
