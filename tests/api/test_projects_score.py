"""T009 — projects feed gains the Feature 4 scoring projection.

Covers: ``score`` present on feed items; ``sort=score`` ordering (desc/asc, NULLS LAST in both
directions); the ``score_min`` / ``score_max`` range filter (which EXCLUDES unscored projects from
the match); and the score filter AND-combining with an existing filter (``qualified_only``).
Read-only over the ORM; each test seeds only what it needs via the conftest factories.
"""
from __future__ import annotations

from mostaql_notifier.db.models import EvalStatus
from tests.api.conftest import make_project, make_project_score


def _get(client, **params):
    resp = client.get("/api/projects", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ids(items) -> list[int]:
    return [it["id"] for it in items]


def _idset(items) -> set[int]:
    return {it["id"] for it in items}


def _by_id(items) -> dict[int, dict]:
    return {it["id"]: it for it in items}


def test_score_present_in_feed_items(api_env):
    with api_env.session() as s:
        scored = make_project(s, _n=1)
        make_project_score(s, project=scored, score=82.5)
        unscored = make_project(s, _n=2)
        s.commit()
        scored_id, unscored_id = scored.id, unscored.id

    c = api_env.client()
    items = _by_id(_get(c)["items"])
    # Scored project carries its latest score; unscored reads null (never coerced to 0).
    assert items[scored_id]["score"] == 82.5
    assert items[unscored_id]["score"] is None


def test_sort_by_score_desc_nulls_last(api_env):
    with api_env.session() as s:
        high = make_project(s, _n=1)
        make_project_score(s, project=high, score=90.0)
        low = make_project(s, _n=2)
        make_project_score(s, project=low, score=30.0)
        unscored = make_project(s, _n=3)  # no score_row -> NULL score
        s.commit()
        high_id, low_id, none_id = high.id, low.id, unscored.id

    c = api_env.client()
    desc = _ids(_get(c, sort="score", order="desc")["items"])
    assert desc[0] == high_id
    assert desc[1] == low_id
    assert desc[-1] == none_id  # NULL sorts last regardless of direction


def test_sort_by_score_asc_nulls_last(api_env):
    with api_env.session() as s:
        high = make_project(s, _n=1)
        make_project_score(s, project=high, score=90.0)
        low = make_project(s, _n=2)
        make_project_score(s, project=low, score=30.0)
        unscored = make_project(s, _n=3)
        s.commit()
        high_id, low_id, none_id = high.id, low.id, unscored.id

    c = api_env.client()
    asc = _ids(_get(c, sort="score", order="asc")["items"])
    assert asc[0] == low_id
    assert asc[1] == high_id
    assert asc[-1] == none_id  # NULL still last on ascending order


def test_score_min_excludes_null_scored(api_env):
    with api_env.session() as s:
        top = make_project(s, _n=1)
        make_project_score(s, project=top, score=80.0)
        bottom = make_project(s, _n=2)
        make_project_score(s, project=bottom, score=40.0)
        unscored = make_project(s, _n=3)
        s.commit()
        top_id, bottom_id, none_id = top.id, bottom.id, unscored.id

    c = api_env.client()
    out = _idset(_get(c, score_min=50)["items"])
    assert out == {top_id}
    # An unscored / non-qualified project is dropped from the match once the filter is set.
    assert bottom_id not in out
    assert none_id not in out
    # Without any score filter the unscored project reappears.
    assert none_id in _idset(_get(c)["items"])


def test_score_max_and_range_filter(api_env):
    with api_env.session() as s:
        lo = make_project(s, _n=1)
        make_project_score(s, project=lo, score=20.0)
        mid = make_project(s, _n=2)
        make_project_score(s, project=mid, score=55.0)
        hi = make_project(s, _n=3)
        make_project_score(s, project=hi, score=95.0)
        unscored = make_project(s, _n=4)
        s.commit()
        lo_id, mid_id, hi_id, none_id = lo.id, mid.id, hi.id, unscored.id

    c = api_env.client()
    assert _idset(_get(c, score_max=60)["items"]) == {lo_id, mid_id}
    rng = _idset(_get(c, score_min=50, score_max=90)["items"])
    assert rng == {mid_id}
    assert hi_id not in rng and lo_id not in rng and none_id not in rng


def test_score_filter_combines_with_qualified_only(api_env):
    with api_env.session() as s:
        match = make_project(s, _n=1, eval_status=EvalStatus.qualified)
        make_project_score(s, project=match, score=85.0)
        # Fails qualified_only (disqualified), though it has a high score.
        not_qualified = make_project(s, _n=2, eval_status=EvalStatus.disqualified)
        make_project_score(s, project=not_qualified, score=85.0)
        # Fails the score floor.
        low_score = make_project(s, _n=3, eval_status=EvalStatus.qualified)
        make_project_score(s, project=low_score, score=20.0)
        s.commit()
        match_id = match.id
        fail_ids = {not_qualified.id, low_score.id}

    c = api_env.client()
    out = _idset(_get(c, qualified_only=True, score_min=50)["items"])
    assert out == {match_id}
    assert out.isdisjoint(fail_ids)


def test_score_param_out_of_range_422(api_env):
    c = api_env.client()
    assert c.get("/api/projects", params={"score_min": -1}).status_code == 422
    assert c.get("/api/projects", params={"score_max": 101}).status_code == 422
