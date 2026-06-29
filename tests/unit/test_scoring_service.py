"""T008 — scoring-service unit tests (scoring/service.py).

Exercises the surface-agnostic service against the real ``db_session`` + seeded ``settings`` fixtures
and the conftest row factories: persistence, the qualified-only backfill, breakdown read-through, and
``/top`` ordering.
"""
from __future__ import annotations

from mostaql_notifier.db.models import EvalStatus, ProjectScore, ProjectStatus
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.scoring import service
from tests.api.conftest import make_client, make_project, make_project_score


def test_score_project_persists_a_row(db_session, settings):
    now = utcnow()
    client = make_client(db_session, _n=1)
    project = make_project(db_session, _n=1, client_id=client.id, eval_status=EvalStatus.qualified)

    row = service.score_project(db_session, project, settings=settings, now_utc=now)

    assert isinstance(row, ProjectScore)
    assert row.project_id == project.id
    assert row.score is not None and 0.0 <= row.score <= 100.0
    assert row.breakdown["components"] and len(row.breakdown["components"]) == 6
    assert row.computed_at == now
    # defaults applied on create — owned by the re-check loop, not this service.
    assert row.outcome.value == "open"
    assert row.tracking_active is True

    fetched = db_session.get(ProjectScore, project.id)
    assert fetched is not None and fetched.score == row.score


def test_score_project_upserts_in_place(db_session, settings):
    now = utcnow()
    client = make_client(db_session, _n=1)
    project = make_project(db_session, _n=1, client_id=client.id)

    first = service.score_project(db_session, project, settings=settings, now_utc=now)
    # change an input then re-score: same row, refreshed value.
    project.bids_count = 99
    second = service.score_project(db_session, project, settings=settings, now_utc=now)

    assert second.project_id == first.project_id
    assert db_session.query(ProjectScore).count() == 1


def test_rescore_all_scores_qualified_skips_disqualified(db_session, settings):
    now = utcnow()
    client = make_client(db_session, _n=1)
    make_project(db_session, _n=1, client_id=client.id, eval_status=EvalStatus.qualified)
    make_project(db_session, _n=2, client_id=client.id, eval_status=EvalStatus.qualified)
    disq = make_project(db_session, _n=3, client_id=client.id, eval_status=EvalStatus.disqualified)

    count = service.rescore_all(db_session, settings=settings, now_utc=now)

    assert count == 2
    assert db_session.query(ProjectScore).count() == 2
    assert db_session.get(ProjectScore, disq.id) is None  # non-qualified left unscored


def test_get_breakdown_round_trip_and_none(db_session, settings):
    now = utcnow()
    project = make_project(db_session, _n=1, eval_status=EvalStatus.qualified)

    assert service.get_breakdown(db_session, project.id) is None  # never scored yet

    service.score_project(db_session, project, settings=settings, now_utc=now)
    bd = service.get_breakdown(db_session, project.id)
    assert bd is not None
    assert bd["score"] == db_session.get(ProjectScore, project.id).breakdown["score"]
    assert len(bd["components"]) == 6


def test_top_open_orders_and_filters(db_session, settings):
    # qualified + open + tracking, distinct scores
    p_hi = make_project(db_session, _n=1, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open)
    p_mid = make_project(db_session, _n=2, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open)
    make_project_score(db_session, project=p_hi, score=90.0, tracking_active=True)
    make_project_score(db_session, project=p_mid, score=80.0, tracking_active=True)

    # excluded: closed
    p_closed = make_project(db_session, _n=3, eval_status=EvalStatus.qualified, site_status=ProjectStatus.closed)
    make_project_score(db_session, project=p_closed, score=99.0, tracking_active=True)
    # excluded: tracking stopped
    p_untracked = make_project(db_session, _n=4, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open)
    make_project_score(db_session, project=p_untracked, score=95.0, tracking_active=False)
    # excluded: not qualified
    p_disq = make_project(db_session, _n=5, eval_status=EvalStatus.disqualified, site_status=ProjectStatus.open)
    make_project_score(db_session, project=p_disq, score=100.0, tracking_active=True)

    rows = service.top_open(db_session, 5)

    assert [p.id for p in rows] == [p_hi.id, p_mid.id]  # desc by score, filtered
    assert rows[0].score_row.score == 90.0  # score_row eager-loaded


def test_top_open_limit(db_session, settings):
    for i in range(1, 4):
        p = make_project(db_session, _n=i, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open)
        make_project_score(db_session, project=p, score=float(50 + i), tracking_active=True)

    assert len(service.top_open(db_session, 2)) == 2
