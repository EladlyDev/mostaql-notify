"""Edge coverage for the Feature 4 scoring projection on the projects feed (GET /api/projects).

Extends ``test_settings_scoring`` / ``test_project_detail_score`` with the LIST-level contract:
``score`` equals the stored value for scored projects and null for unscored; ``freshness`` is derived
only for scored rows; ``sort=score`` orders DESC with NULLs last + paginates; ``score_min``/``score_max``
are inclusive, min>max yields empty, non-numeric → 422, and the range composes with other filters.
"""
from __future__ import annotations

from datetime import datetime, timezone

from mostaql_notifier.db.models import EvalStatus, Outcome, ProjectStatus
from tests.api.conftest import make_project, make_project_score


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _items(api_env, **params):
    resp = api_env.client().get("/api/projects", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_score_field_equals_stored_for_scored_null_for_unscored(api_env):
    with api_env.session() as s:
        scored = make_project(s, _n=1)
        make_project_score(s, project=scored, score=42.5)
        make_project(s, _n=2)  # never scored
        s.commit()
        scored_id = scored.id

    body = _items(api_env)
    by_id = {it["id"]: it for it in body["items"]}
    assert body["total"] == 2
    assert by_id[scored_id]["score"] == 42.5
    # freshness derived (non-null) for a scored row.
    assert by_id[scored_id]["freshness"] is not None
    unscored = next(it for it in body["items"] if it["id"] != scored_id)
    assert unscored["score"] is None
    assert unscored["freshness"] is None


def test_sort_by_score_desc_nulls_last_with_pagination(api_env):
    with api_env.session() as s:
        a = make_project(s, _n=1)
        b = make_project(s, _n=2)
        c = make_project(s, _n=3)
        make_project(s, _n=4)  # unscored -> NULL
        make_project_score(s, project=a, score=90.0)
        make_project_score(s, project=b, score=50.0)
        make_project_score(s, project=c, score=70.0)
        s.commit()
        a_id, b_id, c_id = a.id, b.id, c.id

    # Full ordered set: 90, 70, 50, then the NULL last.
    body = _items(api_env, sort="score", order="desc")
    ids = [it["id"] for it in body["items"]]
    scores = [it["score"] for it in body["items"]]
    assert ids[:3] == [a_id, c_id, b_id]
    assert scores[:3] == [90.0, 70.0, 50.0]
    assert scores[3] is None  # the unscored project sorts LAST

    # Pagination keeps that ordering: page 2 of size 2 is [50.0, None].
    page2 = _items(api_env, sort="score", order="desc", page=2, page_size=2)
    assert page2["page"] == 2
    assert [it["score"] for it in page2["items"]] == [50.0, None]


def test_score_min_max_inclusive_boundaries(api_env):
    with api_env.session() as s:
        for n, sc in [(1, 30.0), (2, 50.0), (3, 70.0), (4, 90.0)]:
            p = make_project(s, _n=n)
            make_project_score(s, project=p, score=sc)
        s.commit()

    # Inclusive lower bound: 50 keeps the 50.0 row.
    got = {it["score"] for it in _items(api_env, score_min=50)["items"]}
    assert got == {50.0, 70.0, 90.0}
    # Inclusive upper bound: 70 keeps the 70.0 row.
    got = {it["score"] for it in _items(api_env, score_max=70)["items"]}
    assert got == {30.0, 50.0, 70.0}
    # Both bounds, inclusive on each end.
    got = {it["score"] for it in _items(api_env, score_min=50, score_max=70)["items"]}
    assert got == {50.0, 70.0}


def test_score_min_greater_than_max_is_empty(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        make_project_score(s, project=p, score=60.0)
        s.commit()

    body = _items(api_env, score_min=80, score_max=40)
    assert body["total"] == 0
    assert body["items"] == []


def test_score_filter_excludes_unscored(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        make_project_score(s, project=p, score=60.0)
        make_project(s, _n=2)  # unscored — dropped whenever a score bound is set
        s.commit()
        scored_id = p.id

    body = _items(api_env, score_min=0)
    assert [it["id"] for it in body["items"]] == [scored_id]


def test_score_non_numeric_is_422(api_env):
    assert api_env.client().get("/api/projects", params={"score_min": "abc"}).status_code == 422
    assert api_env.client().get("/api/projects", params={"score_max": "xyz"}).status_code == 422
    # Out-of-range (registry bounds 0..100) is also rejected.
    assert api_env.client().get("/api/projects", params={"score_min": 150}).status_code == 422
    assert api_env.client().get("/api/projects", params={"score_max": -5}).status_code == 422


def test_score_range_composes_with_eval_and_site_status_filters(api_env):
    with api_env.session() as s:
        # qualified + open + score 80 — the only row that survives every filter below.
        keep = make_project(
            s, _n=1, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open
        )
        make_project_score(s, project=keep, score=80.0)
        # qualified + open but score too low.
        low = make_project(
            s, _n=2, eval_status=EvalStatus.qualified, site_status=ProjectStatus.open
        )
        make_project_score(s, project=low, score=20.0)
        # high score but not qualified.
        notq = make_project(
            s, _n=3, eval_status=EvalStatus.disqualified, site_status=ProjectStatus.open
        )
        make_project_score(s, project=notq, score=85.0)
        s.commit()
        keep_id = keep.id

    body = _items(api_env, score_min=50, qualified_only=True, site_status="open")
    assert [it["id"] for it in body["items"]] == [keep_id]


def test_site_status_filter_accepts_awarded(api_env):
    with api_env.session() as s:
        awarded = make_project(s, _n=1, site_status=ProjectStatus.awarded)
        make_project_score(s, project=awarded, score=55.0, outcome=Outcome.hired)
        make_project(s, _n=2, site_status=ProjectStatus.open)
        s.commit()
        awarded_id = awarded.id

    body = _items(api_env, site_status="awarded")
    assert [it["id"] for it in body["items"]] == [awarded_id]
    assert body["items"][0]["site_status"] == "awarded"
