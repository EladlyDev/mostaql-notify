"""T033 — the derived ``freshness`` "still good?" signal on the feed + detail.

Covers: a fresh, low-bid, open scored project reads ``green`` (feed and detail); a crowded/closed
scored project reads ``red``; an unscored project reads ``null`` (freshness is derived ONLY for a
scored project). Thresholds are the seeded defaults (green ≤ 8 bids & ≤ 12h; red ≥ 20 bids or ≥ 48h
or a closed/awarded/unknown status).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mostaql_notifier.db.models import ProjectStatus
from tests.api.conftest import make_project, make_project_score


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _feed_item(client, pid):
    body = client.get("/api/projects").json()
    return next(it for it in body["items"] if it["id"] == pid)


def test_fresh_low_bid_open_scored_reads_green(api_env):
    with api_env.session() as s:
        p = make_project(
            s, _n=1, site_status=ProjectStatus.open, bids_count=3, posted_at=_now(),
        )
        make_project_score(s, project=p, score=78.0)
        s.commit()
        pid = p.id

    c = api_env.client()
    assert _feed_item(c, pid)["freshness"] == "green"
    assert c.get(f"/api/projects/{pid}").json()["freshness"] == "green"


def test_crowded_closed_scored_reads_red(api_env):
    with api_env.session() as s:
        p = make_project(
            s,
            _n=1,
            site_status=ProjectStatus.closed,
            bids_count=25,  # >= red_min_bids (20)
            posted_at=_now() - timedelta(hours=72),  # >= red_min_age_hours (48)
        )
        make_project_score(s, project=p, score=40.0)
        s.commit()
        pid = p.id

    c = api_env.client()
    assert _feed_item(c, pid)["freshness"] == "red"
    assert c.get(f"/api/projects/{pid}").json()["freshness"] == "red"


def test_unscored_project_reads_null_freshness(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1, site_status=ProjectStatus.open, bids_count=2, posted_at=_now())
        s.commit()  # no score_row
        pid = p.id

    c = api_env.client()
    item = _feed_item(c, pid)
    assert item["score"] is None
    assert item["freshness"] is None
    assert c.get(f"/api/projects/{pid}").json()["freshness"] is None
