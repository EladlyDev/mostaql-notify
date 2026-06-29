"""Exhaustive edge tests for the surface-agnostic scoring service (Feature 4).

Exercises ``scoring/service.py`` against the real ``db_session`` + seeded ``settings`` fixtures and
the conftest row factories. Asserts the contract precisely: upsert-in-place, transaction ownership
(``flush`` but never ``commit``), the qualified-only backfill, breakdown read-through, and the
multi-filter ``/top`` ordering with eager-loaded ``score_row``.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import event

from mostaql_notifier.db.models import EvalStatus, Outcome, ProjectScore, ProjectStatus
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.scoring import service
from tests.api.conftest import (
    make_client,
    make_project,
    make_project_score,
    make_trajectory,
)

# --------------------------------------------------------------------------- score_project


def test_score_project_insert_applies_model_defaults(db_session, settings):
    """First call INSERTs a row carrying the model defaults (outcome=open, tracking_active=True)."""
    now = utcnow()
    client = make_client(db_session, _n=1)
    project = make_project(db_session, _n=1, client_id=client.id, eval_status=EvalStatus.qualified)

    assert db_session.get(ProjectScore, project.id) is None  # nothing before the first call

    row = service.score_project(db_session, project, settings=settings, now_utc=now)

    assert isinstance(row, ProjectScore)
    assert row.project_id == project.id
    assert row.score is not None and 0.0 <= row.score <= 100.0
    assert len(row.breakdown["components"]) == 6
    assert row.computed_at == now
    # the service relies on column defaults for the lifecycle fields it does not own.
    assert row.outcome is Outcome.open
    assert row.tracking_active is True
    assert row.last_checked_at is None


def test_score_project_upsert_preserves_lifecycle_fields(db_session, settings):
    """Second call UPDATEs the same row: refreshes derived fields, never touches the owned ones."""
    now = utcnow()
    earlier = now - timedelta(hours=3)
    project = make_project(db_session, _n=1, eval_status=EvalStatus.qualified)

    # pre-existing row owned by the re-check loop: non-default lifecycle state.
    checked = now - timedelta(minutes=30)
    make_project_score(
        db_session,
        project=project,
        score=None,
        breakdown={},
        computed_at=earlier,
        outcome=Outcome.hired,
        tracking_active=False,
        last_checked_at=checked,
    )

    row = service.score_project(db_session, project, settings=settings, now_utc=now)

    # exactly one row — upsert in place, no duplicate insert.
    assert db_session.query(ProjectScore).count() == 1
    # derived fields refreshed by the service.
    assert row.score is not None
    assert row.breakdown and len(row.breakdown["components"]) == 6
    assert row.computed_at == now
    # lifecycle fields owned by the re-check loop — left exactly as they were.
    assert row.outcome is Outcome.hired
    assert row.tracking_active is False
    assert row.last_checked_at == checked


def test_score_project_returns_the_persisted_row(db_session, settings):
    """The returned object is the same identity-mapped row fetched back from the session."""
    now = utcnow()
    project = make_project(db_session, _n=1, eval_status=EvalStatus.qualified)

    row = service.score_project(db_session, project, settings=settings, now_utc=now)
    fetched = db_session.get(ProjectScore, project.id)

    assert fetched is row
    assert fetched.score == row.score


def test_score_project_flushes_but_does_not_commit(db_session, settings):
    """Transaction ownership: the service only flushes; a rollback discards the new row."""
    now = utcnow()
    project = make_project(db_session, _n=1, eval_status=EvalStatus.qualified)
    pid = project.id

    service.score_project(db_session, project, settings=settings, now_utc=now)
    assert db_session.get(ProjectScore, pid) is not None  # visible after flush

    db_session.rollback()

    assert db_session.query(ProjectScore).count() == 0  # gone — never committed


def test_score_project_idempotent_same_inputs(db_session, settings):
    """Re-scoring with unchanged inputs yields the same score and never duplicates the row."""
    now = utcnow()
    client = make_client(db_session, _n=1)
    project = make_project(db_session, _n=1, client_id=client.id, eval_status=EvalStatus.qualified)

    first = service.score_project(db_session, project, settings=settings, now_utc=now)
    score_1 = first.score
    second = service.score_project(db_session, project, settings=settings, now_utc=now)

    assert second is first
    assert second.score == score_1
    assert db_session.query(ProjectScore).count() == 1


# --------------------------------------------------------------------------- rescore_all


def test_rescore_all_scores_only_qualified(db_session, settings):
    """Only qualified projects are scored; pending/disqualified are left with no row."""
    now = utcnow()
    client = make_client(db_session, _n=1)
    q1 = make_project(db_session, _n=1, client_id=client.id, eval_status=EvalStatus.qualified)
    q2 = make_project(db_session, _n=2, client_id=client.id, eval_status=EvalStatus.qualified)
    pend = make_project(db_session, _n=3, client_id=client.id, eval_status=EvalStatus.pending)
    disq = make_project(db_session, _n=4, client_id=client.id, eval_status=EvalStatus.disqualified)
    base = make_project(db_session, _n=5, client_id=client.id, eval_status=EvalStatus.baseline)

    count = service.rescore_all(db_session, settings=settings, now_utc=now)

    assert count == 2
    assert db_session.query(ProjectScore).count() == 2
    assert db_session.get(ProjectScore, q1.id) is not None
    assert db_session.get(ProjectScore, q2.id) is not None
    for p in (pend, disq, base):
        assert db_session.get(ProjectScore, p.id) is None


def test_rescore_all_handles_missing_client_and_empty_snapshots(db_session, settings):
    """No client and no snapshots must not raise — the model floors the missing inputs."""
    now = utcnow()
    # qualified project with client_id None and no snapshots.
    project = make_project(db_session, _n=1, eval_status=EvalStatus.qualified, client_id=None)

    count = service.rescore_all(db_session, settings=settings, now_utc=now)

    assert count == 1
    row = db_session.get(ProjectScore, project.id)
    assert row is not None and row.score is not None
    assert 0.0 <= row.score <= 100.0


def test_rescore_all_empty_db_returns_zero(db_session, settings):
    assert service.rescore_all(db_session, settings=settings, now_utc=utcnow()) == 0


def test_rescore_all_idempotent_no_dup_rows(db_session, settings):
    """Running twice gives identical scores and exactly one row per qualified project."""
    now = utcnow()
    client = make_client(db_session, _n=1)
    p1 = make_project(db_session, _n=1, client_id=client.id, eval_status=EvalStatus.qualified)
    p2 = make_project(db_session, _n=2, client_id=client.id, eval_status=EvalStatus.qualified)
    # give p2 a trajectory so the competition velocity path is exercised across runs.
    make_trajectory(
        db_session,
        p2,
        [
            (now - timedelta(hours=4), 1, ProjectStatus.open, 50.0),
            (now - timedelta(hours=1), 5, ProjectStatus.open, 55.0),
        ],
    )

    first = service.rescore_all(db_session, settings=settings, now_utc=now)
    scores_1 = {
        r.project_id: r.score for r in db_session.query(ProjectScore).all()
    }
    second = service.rescore_all(db_session, settings=settings, now_utc=now)
    scores_2 = {
        r.project_id: r.score for r in db_session.query(ProjectScore).all()
    }

    assert first == second == 2
    assert db_session.query(ProjectScore).count() == 2
    assert scores_1 == scores_2
    assert set(scores_1) == {p1.id, p2.id}


def test_rescore_all_does_not_commit(db_session, settings):
    now = utcnow()
    make_project(db_session, _n=1, eval_status=EvalStatus.qualified)

    service.rescore_all(db_session, settings=settings, now_utc=now)
    db_session.rollback()

    assert db_session.query(ProjectScore).count() == 0


# --------------------------------------------------------------------------- get_breakdown


def test_get_breakdown_none_when_no_row(db_session, settings):
    project = make_project(db_session, _n=1, eval_status=EvalStatus.qualified)
    assert service.get_breakdown(db_session, project.id) is None


def test_get_breakdown_none_when_row_exists_but_unscored(db_session, settings):
    """A lifecycle row may exist with ``score is None`` (created but not yet scored)."""
    project = make_project(db_session, _n=1, eval_status=EvalStatus.qualified)
    make_project_score(db_session, project=project, score=None, breakdown={})

    assert service.get_breakdown(db_session, project.id) is None


def test_get_breakdown_returns_stored_dict_verbatim(db_session, settings):
    """Once scored, the stored breakdown dict is returned exactly as persisted."""
    now = utcnow()
    client = make_client(db_session, _n=1)
    project = make_project(db_session, _n=1, client_id=client.id, eval_status=EvalStatus.qualified)
    row = service.score_project(db_session, project, settings=settings, now_utc=now)

    bd = service.get_breakdown(db_session, project.id)

    assert bd is row.breakdown  # same object, no re-derivation
    assert bd["score"] == round(row.score, 2)  # breakdown echoes the rounded score
    assert len(bd["components"]) == 6


def test_get_breakdown_unknown_project_id(db_session, settings):
    assert service.get_breakdown(db_session, 999_999) is None


# --------------------------------------------------------------------------- top_open


def test_top_open_orders_desc_and_applies_every_filter(db_session, settings):
    """Build a spread proving each filter independently, and the score-desc ordering."""
    # included: qualified + open + tracking, distinct scores (proves ordering).
    hi = make_project(db_session, _n=1, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open)
    mid = make_project(db_session, _n=2, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open)
    lo = make_project(db_session, _n=3, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open)
    make_project_score(db_session, project=hi, score=90.0, tracking_active=True)
    make_project_score(db_session, project=mid, score=80.0, tracking_active=True)
    make_project_score(db_session, project=lo, score=70.0, tracking_active=True)

    # excluded — closed site_status.
    closed = make_project(db_session, _n=4, eval_status=EvalStatus.qualified, site_status=ProjectStatus.closed)
    make_project_score(db_session, project=closed, score=99.0, tracking_active=True)
    # excluded — awarded site_status.
    awarded = make_project(db_session, _n=5, eval_status=EvalStatus.qualified, site_status=ProjectStatus.awarded)
    make_project_score(db_session, project=awarded, score=98.0, tracking_active=True)
    # excluded — tracking stopped.
    untracked = make_project(db_session, _n=6, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open)
    make_project_score(db_session, project=untracked, score=97.0, tracking_active=False)
    # excluded — not qualified.
    disq = make_project(db_session, _n=7, eval_status=EvalStatus.disqualified, site_status=ProjectStatus.open)
    make_project_score(db_session, project=disq, score=100.0, tracking_active=True)
    # excluded — never scored (inner join on score_row).
    make_project(db_session, _n=8, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open)

    rows = service.top_open(db_session, 10)

    assert [p.id for p in rows] == [hi.id, mid.id, lo.id]


def test_top_open_respects_limit(db_session, settings):
    for i in range(1, 6):
        p = make_project(db_session, _n=i, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open)
        make_project_score(db_session, project=p, score=float(50 + i), tracking_active=True)

    rows = service.top_open(db_session, 2)
    assert len(rows) == 2
    # the two highest scores (55, 54) in desc order.
    assert [r.score_row.score for r in rows] == [55.0, 54.0]


def test_top_open_zero_returns_empty(db_session, settings):
    p = make_project(db_session, _n=1, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open)
    make_project_score(db_session, project=p, score=90.0, tracking_active=True)

    assert service.top_open(db_session, 0) == []


def test_top_open_empty_when_nothing_eligible(db_session, settings):
    # qualified + open but never scored ⇒ excluded by the inner join.
    make_project(db_session, _n=1, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open)
    assert service.top_open(db_session, 5) == []


def test_top_open_eager_loads_score_row_without_new_query(db_session, settings):
    """Accessing ``.score_row`` on a returned project must not emit a fresh SQL statement."""
    hi = make_project(db_session, _n=1, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open)
    mid = make_project(db_session, _n=2, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open)
    make_project_score(db_session, project=hi, score=90.0, tracking_active=True)
    make_project_score(db_session, project=mid, score=80.0, tracking_active=True)

    rows = service.top_open(db_session, 5)

    statements: list[str] = []

    def _record(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    bind = db_session.get_bind()
    event.listen(bind, "after_cursor_execute", _record)
    try:
        loaded = [r.score_row.score for r in rows]
    finally:
        event.remove(bind, "after_cursor_execute", _record)

    assert loaded == [90.0, 80.0]
    assert statements == []  # contains_eager populated score_row up front
