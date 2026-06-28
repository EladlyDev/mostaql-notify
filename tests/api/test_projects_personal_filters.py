"""The projects feed's personal projection + filters (Feature 3, US1, T016).

Verifies that ``GET /api/projects`` LEFT-JOINs the personal record (defaulting record-less projects),
and that ``personal_status`` / ``favorites_only`` / ``include_hidden`` filter correctly and compose
with Feature 2's existing filters. Hidden projects are excluded unless ``include_hidden=true``.
"""
from __future__ import annotations

from tests.api.conftest import make_personal_record, make_project


def _ids(payload) -> set[int]:
    return {it["id"] for it in payload["items"]}


def _get(client, **params):
    return client.get("/api/projects", params=params).json()


def test_projection_defaulted_when_no_record(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        s.commit()
        pid = p.id
    c = api_env.client()
    item = next(it for it in _get(c)["items"] if it["id"] == pid)
    assert item["favorite"] is False
    assert item["personal_status"] == "new"
    assert item["personal_status_label"] == "جديد"  # Arabic label resolved from config
    assert item["tags"] == []
    assert item["hidden"] is False


def test_projection_reflects_record(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        make_personal_record(
            s, project=p, favorite=True, status="applied", tags=["عاجل", "تصميم"]
        )
        s.commit()
        pid = p.id
    c = api_env.client()
    item = next(it for it in _get(c)["items"] if it["id"] == pid)
    assert item["favorite"] is True
    assert item["personal_status"] == "applied"
    assert item["personal_status_label"] == "تقدّمت"
    assert item["tags"] == ["عاجل", "تصميم"]


def test_personal_status_filter(api_env):
    with api_env.session() as s:
        a = make_project(s, _n=1)  # no record -> counts as "new"
        b = make_project(s, _n=2)
        make_personal_record(s, project=b, status="interested")
        s.commit()
        a_id, b_id = a.id, b.id
    c = api_env.client()
    assert _ids(_get(c, personal_status="interested")) == {b_id}
    # A record-less project counts as the default status "new".
    assert a_id in _ids(_get(c, personal_status="new"))
    assert b_id not in _ids(_get(c, personal_status="new"))


def test_favorites_only_filter(api_env):
    with api_env.session() as s:
        a = make_project(s, _n=1)
        b = make_project(s, _n=2)
        make_personal_record(s, project=a, favorite=True)
        make_personal_record(s, project=b, favorite=False)
        s.commit()
        a_id, b_id = a.id, b.id
    c = api_env.client()
    out = _ids(_get(c, favorites_only=True))
    assert a_id in out and b_id not in out


def test_hidden_excluded_by_default_and_shown_with_flag(api_env):
    with api_env.session() as s:
        visible = make_project(s, _n=1)
        gone = make_project(s, _n=2)
        make_personal_record(s, project=gone, hidden=True)
        s.commit()
        visible_id, gone_id = visible.id, gone.id
    c = api_env.client()
    default = _ids(_get(c))
    assert visible_id in default and gone_id not in default  # hidden excluded by default
    with_hidden = _ids(_get(c, include_hidden=True))
    assert gone_id in with_hidden  # surfaced by the show-hidden view


def test_personal_filter_composes_with_feature2_filter(api_env):
    with api_env.session() as s:
        keep = make_project(s, _n=1, tier=1)
        make_personal_record(s, project=keep, favorite=True)
        other_tier = make_project(s, _n=2, tier=2)
        make_personal_record(s, project=other_tier, favorite=True)
        s.commit()
        keep_id, other_id = keep.id, other_tier.id
    c = api_env.client()
    out = _ids(_get(c, favorites_only=True, tier=1))
    assert keep_id in out and other_id not in out  # AND-composed with the tier filter


def test_filters_require_auth(api_env):
    c = api_env.client(auth_enabled=True, password="pw")
    assert c.get("/api/projects", params={"favorites_only": True}).status_code == 401
