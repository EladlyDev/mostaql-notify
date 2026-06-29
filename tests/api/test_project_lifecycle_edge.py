"""Edge coverage for GET /api/projects/{id}/lifecycle (Feature 4).

Extends ``test_project_lifecycle`` with: per-snapshot bids_count/site_status/score fidelity; a longer
dedupe series (consecutive identical statuses collapse, first timestamp kept, status flapping emits a
fresh event); the outcome echo; the empty-but-200 shape; the 404 path; and auth parity with sibling
endpoints (gate when enabled, unlocks after login).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mostaql_notifier.db.models import Outcome, ProjectStatus
from tests.api.conftest import make_project, make_project_score, make_trajectory


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_snapshots_carry_bids_status_and_score_in_order(api_env):
    now = _now()
    pts = [
        (now - timedelta(hours=3), 1, ProjectStatus.open, 80.0),
        (now - timedelta(hours=2), 6, ProjectStatus.open, 72.0),
        (now - timedelta(hours=1), 9, ProjectStatus.awarded, 70.0),
    ]
    with api_env.session() as s:
        p = make_project(s, _n=1)
        make_trajectory(s, p, pts)
        s.commit()
        pid = p.id

    snaps = api_env.client().get(f"/api/projects/{pid}/lifecycle").json()["snapshots"]
    assert [snap["bids_count"] for snap in snaps] == [1, 6, 9]
    assert [snap["site_status"] for snap in snaps] == ["open", "open", "awarded"]
    assert [snap["score"] for snap in snaps] == [80.0, 72.0, 70.0]
    captured = [snap["captured_at"] for snap in snaps]
    assert captured == sorted(captured)


def test_status_timeline_dedupes_and_keeps_first_timestamp_with_flapping(api_env):
    now = _now()
    # open, open, open, awarded, awarded, open  — runs collapse; the re-entry into open is a NEW event.
    t = [now + timedelta(hours=i) for i in range(6)]
    pts = [
        (t[0], 1, ProjectStatus.open, 70.0),
        (t[1], 2, ProjectStatus.open, 70.0),
        (t[2], 3, ProjectStatus.open, 70.0),
        (t[3], 4, ProjectStatus.awarded, 70.0),
        (t[4], 5, ProjectStatus.awarded, 70.0),
        (t[5], 6, ProjectStatus.open, 70.0),
    ]
    with api_env.session() as s:
        p = make_project(s, _n=1)
        make_trajectory(s, p, pts)
        s.commit()
        pid = p.id

    timeline = api_env.client().get(f"/api/projects/{pid}/lifecycle").json()["status_timeline"]
    assert [ev["status"] for ev in timeline] == ["open", "awarded", "open"]
    # First "open" event keeps the FIRST snapshot's timestamp (t[0]), not t[1]/t[2].
    snaps = api_env.client().get(f"/api/projects/{pid}/lifecycle").json()["snapshots"]
    assert timeline[0]["at"] == snaps[0]["captured_at"]
    assert timeline[1]["at"] == snaps[3]["captured_at"]  # first awarded
    assert timeline[2]["at"] == snaps[5]["captured_at"]  # re-entry into open


def test_outcome_echoed_from_score_row(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        make_trajectory(s, p, [(_now(), 3, ProjectStatus.closed, 50.0)])
        make_project_score(s, project=p, score=50.0, outcome=Outcome.hired)
        s.commit()
        pid = p.id

    body = api_env.client().get(f"/api/projects/{pid}/lifecycle").json()
    assert body["outcome"] == "hired"


def test_empty_trajectory_returns_200_with_empty_arrays(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        s.commit()
        pid = p.id

    resp = api_env.client().get(f"/api/projects/{pid}/lifecycle")
    assert resp.status_code == 200
    body = resp.json()
    assert body["snapshots"] == []
    assert body["status_timeline"] == []
    assert body["outcome"] is None


def test_unknown_id_is_404(api_env):
    resp = api_env.client().get("/api/projects/424242/lifecycle")
    assert resp.status_code == 404


def test_lifecycle_auth_enforced_like_siblings(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        make_trajectory(s, p, [(_now(), 3, ProjectStatus.open, 70.0)])
        s.commit()
        pid = p.id

    client = api_env.client(auth_enabled=True, password="pw")
    # Locked before login.
    assert client.get(f"/api/projects/{pid}/lifecycle").status_code == 401
    # Unlocks after login (cookie persisted on the TestClient).
    assert client.post("/api/auth/login", json={"password": "pw"}).status_code == 200
    assert client.get(f"/api/projects/{pid}/lifecycle").status_code == 200
