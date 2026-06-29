"""T025 — GET /api/projects/{id}/lifecycle.

Covers: the time-ordered append-only ``snapshots`` trajectory; the ``status_timeline`` as the DEDUPED
series of site-status transitions (one event per change, the first snapshot seeding it); ``outcome``
surfaced from the stored score row; the empty-trajectory shape; and the 404 path. Built from
``make_trajectory`` per the conftest tuple form ``(captured_at, bids_count, site_status, score)``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mostaql_notifier.db.models import Outcome, ProjectStatus
from tests.api.conftest import make_project, make_project_score, make_trajectory


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_lifecycle_snapshots_timeline_and_outcome(api_env):
    now = _now()
    t0 = now - timedelta(hours=3)
    t1 = now - timedelta(hours=2)
    t2 = now - timedelta(hours=1)
    with api_env.session() as s:
        p = make_project(s, _n=1)
        # open -> open -> closed, with bids climbing (out-of-order insert to prove server ordering).
        make_trajectory(
            s,
            p,
            [
                (t1, 5, ProjectStatus.open, 65.0),
                (t0, 2, ProjectStatus.open, 70.0),
                (t2, 12, ProjectStatus.closed, 60.0),
            ],
        )
        make_project_score(s, project=p, score=60.0, outcome=Outcome.closed_no_hire)
        s.commit()
        pid = p.id

    body = api_env.client().get(f"/api/projects/{pid}/lifecycle").json()

    # snapshots: all three, oldest first, bids climbing 2 -> 5 -> 12.
    snaps = body["snapshots"]
    assert [snap["bids_count"] for snap in snaps] == [2, 5, 12]
    captured = [snap["captured_at"] for snap in snaps]
    assert captured == sorted(captured)
    assert [snap["site_status"] for snap in snaps] == ["open", "open", "closed"]

    # status_timeline: DEDUPED transitions — open (at t0), then closed (at t2). The middle open
    # snapshot at t1 produces no event because the status did not change.
    timeline = body["status_timeline"]
    assert [ev["status"] for ev in timeline] == ["open", "closed"]
    assert timeline[0]["at"] == snaps[0]["captured_at"]
    assert timeline[1]["at"] == snaps[2]["captured_at"]

    # outcome surfaced from the stored score row.
    assert body["outcome"] == "closed_no_hire"


def test_lifecycle_empty_trajectory(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)  # no snapshots, no score row
        s.commit()
        pid = p.id

    body = api_env.client().get(f"/api/projects/{pid}/lifecycle").json()
    assert body["snapshots"] == []
    assert body["status_timeline"] == []
    assert body["outcome"] is None  # never scored/tracked


def test_lifecycle_empty_trajectory_with_stored_outcome(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        make_project_score(s, project=p, score=50.0, outcome=Outcome.open)
        s.commit()
        pid = p.id

    body = api_env.client().get(f"/api/projects/{pid}/lifecycle").json()
    assert body["snapshots"] == []
    assert body["status_timeline"] == []
    assert body["outcome"] == "open"  # defaults to the stored value


def test_lifecycle_404_for_missing_project(api_env):
    resp = api_env.client().get("/api/projects/999999/lifecycle")
    assert resp.status_code == 404
    assert resp.json()["detail"]
