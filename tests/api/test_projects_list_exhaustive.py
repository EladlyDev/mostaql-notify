"""Exhaustive contract tests for ``GET /api/projects``.

Covers every filter (in isolation, boundary-inclusive), the LIKE-escaping behaviour of ``q``,
all four sort keys (asc/desc + NULLs-last in both directions), pagination, enum/range 422s,
AND-combination of filters, and the per-item response shape. Read-only over Feature 1's ORM;
each test seeds only what it needs via the conftest factories.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from mostaql_notifier.db.models import EvalStatus, ProjectStatus
from tests.api.conftest import make_client, make_project


def _ids(items) -> list[int]:
    return [it["id"] for it in items]


def _idset(items) -> set[int]:
    return {it["id"] for it in items}


def _get(client, **params):
    """GET /api/projects with query params; assert 200 and return parsed body."""
    resp = client.get("/api/projects", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# tier
# --------------------------------------------------------------------------- #

def test_tier_filter_isolates_matching_tier(api_env):
    with api_env.session() as s:
        t1 = make_project(s, _n=1, tier=1)
        t2 = make_project(s, _n=2, tier=2)
        tnull = make_project(s, _n=3, tier=None)
        s.commit()
        t1_id, t2_id, tnull_id = t1.id, t2.id, tnull.id
    c = api_env.client()
    assert _idset(_get(c, tier=1)["items"]) == {t1_id}
    assert _idset(_get(c, tier=2)["items"]) == {t2_id}
    # No filter -> all three appear.
    assert _idset(_get(c)["items"]) == {t1_id, t2_id, tnull_id}


@pytest.mark.parametrize("bad", [0, 3, -1])
def test_tier_out_of_range_422(api_env, bad):
    c = api_env.client()
    assert c.get("/api/projects", params={"tier": bad}).status_code == 422


# --------------------------------------------------------------------------- #
# budget (both filters compare on budget_max, inclusive)
# --------------------------------------------------------------------------- #

def test_budget_min_inclusive_on_budget_max(api_env):
    with api_env.session() as s:
        low = make_project(s, _n=1, budget_max=100)
        exact = make_project(s, _n=2, budget_max=500)
        high = make_project(s, _n=3, budget_max=900)
        s.commit()
        low_id, exact_id, high_id = low.id, exact.id, high.id
    c = api_env.client()
    # budget_min == a project's budget_max is INCLUDED.
    out = _idset(_get(c, budget_min=500)["items"])
    assert out == {exact_id, high_id}
    assert low_id not in out


def test_budget_max_inclusive_on_budget_max(api_env):
    with api_env.session() as s:
        low = make_project(s, _n=1, budget_max=100)
        exact = make_project(s, _n=2, budget_max=500)
        high = make_project(s, _n=3, budget_max=900)
        s.commit()
        low_id, exact_id, high_id = low.id, exact.id, high.id
    c = api_env.client()
    out = _idset(_get(c, budget_max=500)["items"])
    assert out == {low_id, exact_id}
    assert high_id not in out


def test_budget_range_combined(api_env):
    with api_env.session() as s:
        a = make_project(s, _n=1, budget_max=100)
        b = make_project(s, _n=2, budget_max=300)
        d = make_project(s, _n=3, budget_max=700)
        s.commit()
        a_id, b_id, d_id = a.id, b.id, d.id
    c = api_env.client()
    out = _idset(_get(c, budget_min=200, budget_max=500)["items"])
    assert out == {b_id}
    assert a_id not in out and d_id not in out


def test_budget_filters_exclude_null_budget_max(api_env):
    """A project with budget_max=None is excluded by either budget bound."""
    with api_env.session() as s:
        nob = make_project(s, _n=1, budget_max=None)
        has = make_project(s, _n=2, budget_max=400)
        s.commit()
        nob_id, has_id = nob.id, has.id
    c = api_env.client()
    assert _idset(_get(c, budget_min=1)["items"]) == {has_id}
    assert _idset(_get(c, budget_max=10000)["items"]) == {has_id}
    # With no budget filter the null-budget project still appears.
    assert nob_id in _idset(_get(c)["items"])


# --------------------------------------------------------------------------- #
# min_hiring_rate
# --------------------------------------------------------------------------- #

def test_min_hiring_rate_inclusive_boundary(api_env):
    with api_env.session() as s:
        c_low = make_client(s, _n=1, hiring_rate=40.0)
        c_exact = make_client(s, _n=2, hiring_rate=60.0)
        c_high = make_client(s, _n=3, hiring_rate=90.0)
        p_low = make_project(s, _n=1, client_id=c_low.id)
        p_exact = make_project(s, _n=2, client_id=c_exact.id)
        p_high = make_project(s, _n=3, client_id=c_high.id)
        s.commit()
        low_id, exact_id, high_id = p_low.id, p_exact.id, p_high.id
    c = api_env.client()
    out = _idset(_get(c, min_hiring_rate=60)["items"])
    assert out == {exact_id, high_id}
    assert low_id not in out


def test_min_hiring_rate_excludes_null_rate_and_clientless(api_env):
    with api_env.session() as s:
        c_good = make_client(s, _n=1, hiring_rate=75.0)
        c_null = make_client(s, _n=2, hiring_rate=None)
        p_good = make_project(s, _n=1, client_id=c_good.id)
        p_nullrate = make_project(s, _n=2, client_id=c_null.id)
        p_clientless = make_project(s, _n=3, client_id=None)
        s.commit()
        good_id, nullrate_id, clientless_id = p_good.id, p_nullrate.id, p_clientless.id
    c = api_env.client()
    # min_hiring_rate set: only the project with a real rate >= threshold survives.
    out = _idset(_get(c, min_hiring_rate=50)["items"])
    assert out == {good_id}
    assert nullrate_id not in out
    assert clientless_id not in out
    # Without the filter, the null-rate AND client-less projects both reappear.
    no_filter = _idset(_get(c)["items"])
    assert {good_id, nullrate_id, clientless_id} <= no_filter


@pytest.mark.parametrize("bad", [-1, 101, 200])
def test_min_hiring_rate_out_of_range_422(api_env, bad):
    c = api_env.client()
    assert c.get("/api/projects", params={"min_hiring_rate": bad}).status_code == 422


def test_min_hiring_rate_zero_is_valid_and_includes_zero_rate(api_env):
    with api_env.session() as s:
        c0 = make_client(s, _n=1, hiring_rate=0.0)
        cn = make_client(s, _n=2, hiring_rate=None)
        p0 = make_project(s, _n=1, client_id=c0.id)
        pn = make_project(s, _n=2, client_id=cn.id)
        s.commit()
        zero_id, null_id = p0.id, pn.id
    c = api_env.client()
    out = _idset(_get(c, min_hiring_rate=0)["items"])
    # 0.0 hiring_rate >= 0 is included; null is still excluded once the filter is present.
    assert zero_id in out
    assert null_id not in out


# --------------------------------------------------------------------------- #
# bids_min / bids_max
# --------------------------------------------------------------------------- #

def test_bids_min_max_inclusive_boundaries(api_env):
    with api_env.session() as s:
        p0 = make_project(s, _n=1, bids_count=0)
        p5 = make_project(s, _n=2, bids_count=5)
        p10 = make_project(s, _n=3, bids_count=10)
        s.commit()
        id0, id5, id10 = p0.id, p5.id, p10.id
    c = api_env.client()
    assert _idset(_get(c, bids_min=5)["items"]) == {id5, id10}
    assert _idset(_get(c, bids_max=5)["items"]) == {id0, id5}
    assert _idset(_get(c, bids_min=5, bids_max=5)["items"]) == {id5}
    assert _idset(_get(c, bids_min=0)["items"]) == {id0, id5, id10}


def test_bids_min_negative_422(api_env):
    c = api_env.client()
    assert c.get("/api/projects", params={"bids_min": -1}).status_code == 422
    assert c.get("/api/projects", params={"bids_max": -1}).status_code == 422


# --------------------------------------------------------------------------- #
# posted_within_hours
# --------------------------------------------------------------------------- #

def test_posted_within_hours_window(api_env):
    now = _now()
    with api_env.session() as s:
        recent = make_project(s, _n=1, posted_at=now - timedelta(hours=1))
        # Just inside a 24h window.
        edge_in = make_project(s, _n=2, posted_at=now - timedelta(hours=23))
        # Clearly outside a 24h window.
        old = make_project(s, _n=3, posted_at=now - timedelta(hours=48))
        s.commit()
        recent_id, edge_in_id, old_id = recent.id, edge_in.id, old.id
    c = api_env.client()
    out = _idset(_get(c, posted_within_hours=24)["items"])
    assert recent_id in out
    assert edge_in_id in out
    assert old_id not in out


def test_posted_within_hours_excludes_null_posted_at(api_env):
    now = _now()
    with api_env.session() as s:
        recent = make_project(s, _n=1, posted_at=now - timedelta(hours=1))
        nodate = make_project(s, _n=2, posted_at=None)
        s.commit()
        recent_id, nodate_id = recent.id, nodate.id
    c = api_env.client()
    out = _idset(_get(c, posted_within_hours=24)["items"])
    assert out == {recent_id}
    assert nodate_id not in out


def test_posted_within_hours_zero_422(api_env):
    c = api_env.client()
    assert c.get("/api/projects", params={"posted_within_hours": 0}).status_code == 422
    assert c.get("/api/projects", params={"posted_within_hours": -5}).status_code == 422


# --------------------------------------------------------------------------- #
# site_status
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "status_enum,value",
    [
        (ProjectStatus.open, "open"),
        (ProjectStatus.closed, "closed"),
        (ProjectStatus.unknown, "unknown"),
    ],
)
def test_site_status_each_value(api_env, status_enum, value):
    with api_env.session() as s:
        target = make_project(s, _n=1, site_status=status_enum)
        # Two distractors with the other statuses.
        others = [st for st in ProjectStatus if st is not status_enum]
        d1 = make_project(s, _n=2, site_status=others[0])
        d2 = make_project(s, _n=3, site_status=others[1])
        s.commit()
        target_id, d1_id, d2_id = target.id, d1.id, d2.id
    c = api_env.client()
    out = _idset(_get(c, site_status=value)["items"])
    assert out == {target_id}
    assert d1_id not in out and d2_id not in out


def test_site_status_invalid_422(api_env):
    c = api_env.client()
    assert c.get("/api/projects", params={"site_status": "bad"}).status_code == 422


# --------------------------------------------------------------------------- #
# qualified_only
# --------------------------------------------------------------------------- #

def test_qualified_only_true_filters_to_qualified(api_env):
    with api_env.session() as s:
        qual = make_project(s, _n=1, eval_status=EvalStatus.qualified)
        base = make_project(s, _n=2, eval_status=EvalStatus.baseline)
        pend = make_project(s, _n=3, eval_status=EvalStatus.pending)
        disq = make_project(s, _n=4, eval_status=EvalStatus.disqualified)
        err = make_project(s, _n=5, eval_status=EvalStatus.eval_error)
        s.commit()
        ids = {
            "qual": qual.id, "base": base.id, "pend": pend.id,
            "disq": disq.id, "err": err.id,
        }
    c = api_env.client()
    out = _idset(_get(c, qualified_only=True)["items"])
    assert out == {ids["qual"]}


def test_qualified_only_false_returns_all(api_env):
    with api_env.session() as s:
        qual = make_project(s, _n=1, eval_status=EvalStatus.qualified)
        base = make_project(s, _n=2, eval_status=EvalStatus.baseline)
        s.commit()
        qual_id, base_id = qual.id, base.id
    c = api_env.client()
    out = _idset(_get(c, qualified_only=False)["items"])
    assert {qual_id, base_id} <= out
    # default (omitted) behaves like false too.
    assert {qual_id, base_id} <= _idset(_get(c)["items"])


def test_qualified_flag_only_true_for_qualified(api_env):
    with api_env.session() as s:
        rows = {
            st: make_project(s, _n=i + 1, eval_status=st).id
            for i, st in enumerate(EvalStatus)
        }
        s.commit()
    c = api_env.client()
    by_id = {it["id"]: it for it in _get(c)["items"]}
    for st, pid in rows.items():
        assert by_id[pid]["qualified"] is (st == EvalStatus.qualified)
        assert by_id[pid]["eval_status"] == st.value


# --------------------------------------------------------------------------- #
# q free-text search + LIKE escaping
# --------------------------------------------------------------------------- #

def test_q_empty_string_is_no_filter(api_env):
    with api_env.session() as s:
        a = make_project(s, _n=1, title="alpha")
        b = make_project(s, _n=2, title="beta")
        s.commit()
        a_id, b_id = a.id, b.id
    c = api_env.client()
    assert _idset(_get(c, q="")["items"]) == {a_id, b_id}


def test_q_substring_latin_in_skills(api_env):
    with api_env.session() as s:
        hit = make_project(s, _n=1, title="X", description="Y", skills=["python", "django"])
        miss = make_project(s, _n=2, title="X", description="Y", skills=["ruby"])
        s.commit()
        hit_id, miss_id = hit.id, miss.id
    c = api_env.client()
    out = _idset(_get(c, q="djan")["items"])
    assert out == {hit_id}
    assert miss_id not in out


def test_q_substring_arabic(api_env):
    with api_env.session() as s:
        hit = make_project(s, _n=1, title="تطوير موقع إلكتروني", description="x", skills=["a"])
        miss = make_project(s, _n=2, title="حملة تسويقية", description="y", skills=["b"])
        s.commit()
        hit_id, miss_id = hit.id, miss.id
    c = api_env.client()
    out = _idset(_get(c, q="موقع")["items"])
    assert out == {hit_id}
    assert miss_id not in out


def test_q_matches_description(api_env):
    with api_env.session() as s:
        hit = make_project(s, _n=1, title="zzz", description="needle in haystack", skills=["a"])
        miss = make_project(s, _n=2, title="zzz", description="plain text", skills=["b"])
        s.commit()
        hit_id, miss_id = hit.id, miss.id
    c = api_env.client()
    assert _idset(_get(c, q="needle")["items"]) == {hit_id}
    assert miss_id not in _idset(_get(c, q="needle")["items"])


def test_q_percent_matches_only_literal_percent(api_env):
    with api_env.session() as s:
        literal = make_project(s, _n=1, title="50% discount", description="x", skills=["a"])
        plain1 = make_project(s, _n=2, title="alpha", description="y", skills=["b"])
        plain2 = make_project(s, _n=3, title="beta", description="z", skills=["c"])
        s.commit()
        literal_id, p1_id, p2_id = literal.id, plain1.id, plain2.id
    c = api_env.client()
    out = _idset(_get(c, q="%")["items"])
    # Must NOT match everything — only the row literally containing '%'.
    assert out == {literal_id}
    assert p1_id not in out and p2_id not in out


def test_q_underscore_matches_only_literal_underscore(api_env):
    with api_env.session() as s:
        literal = make_project(s, _n=1, title="foo_bar", description="x", skills=["a"])
        plain = make_project(s, _n=2, title="fooXbar", description="y", skills=["b"])
        s.commit()
        literal_id, plain_id = literal.id, plain.id
    c = api_env.client()
    out = _idset(_get(c, q="_")["items"])
    assert literal_id in out
    # 'fooXbar' must NOT be matched by a literal underscore search.
    assert plain_id not in out


def test_q_underscore_term_is_literal_not_wildcard(api_env):
    """A term like 'a_b' must match 'a_b' but not 'axb' (underscore is escaped)."""
    with api_env.session() as s:
        exact = make_project(s, _n=1, title="a_b widget", description="x", skills=["a"])
        wild = make_project(s, _n=2, title="axb widget", description="y", skills=["b"])
        s.commit()
        exact_id, wild_id = exact.id, wild.id
    c = api_env.client()
    out = _idset(_get(c, q="a_b")["items"])
    assert out == {exact_id}
    assert wild_id not in out


def test_q_backslash_is_literal(api_env):
    with api_env.session() as s:
        hit = make_project(s, _n=1, title=r"path\to\file", description="x", skills=["a"])
        miss = make_project(s, _n=2, title="pathtofile", description="y", skills=["b"])
        s.commit()
        hit_id, miss_id = hit.id, miss.id
    c = api_env.client()
    out = _idset(_get(c, q="\\")["items"])
    assert hit_id in out
    assert miss_id not in out


def test_q_non_match_excluded(api_env):
    with api_env.session() as s:
        make_project(s, _n=1, title="alpha", description="beta", skills=["gamma"])
        s.commit()
    c = api_env.client()
    assert _get(c, q="nonexistent-term-xyz")["items"] == []


# --------------------------------------------------------------------------- #
# Sorting (asc/desc + NULLs last in BOTH directions) for all 4 keys
# --------------------------------------------------------------------------- #

def _order_with_null(api_env, *, field, values, null_value):
    """Seed projects (one with NULL in the sort field) and return id->value map + null id."""
    ids = []
    null_id = None
    with api_env.session() as s:
        for i, v in enumerate(values):
            kwargs = {field: v}
            p = make_project(s, _n=i + 1, **kwargs)
            ids.append((p.id, v))
        np_ = make_project(s, _n=len(values) + 1, **{field: null_value})
        s.commit()
        ids = [(pid, v) for pid, v in ids]
        null_id = np_.id
    return ids, null_id


@pytest.mark.parametrize("sort_key,field", [
    ("posted_at", "posted_at"),
    ("budget", "budget_max"),
    ("bids_count", "bids_count"),
])
def test_sort_project_columns_nulls_last_both_directions(api_env, sort_key, field):
    now = _now()
    if field == "posted_at":
        values = [now - timedelta(hours=3), now - timedelta(hours=2), now - timedelta(hours=1)]
    elif field == "budget_max":
        values = [100, 200, 300]
    else:  # bids_count
        values = [1, 2, 3]
    seeded, null_id = _order_with_null(api_env, field=field, values=values, null_value=None)
    # rank by value ascending
    asc_ids = [pid for pid, _ in sorted(seeded, key=lambda t: t[1])]
    desc_ids = list(reversed(asc_ids))

    c = api_env.client()
    asc = _ids(_get(c, sort=sort_key, order="asc")["items"])
    desc = _ids(_get(c, sort=sort_key, order="desc")["items"])

    # NULL row is always last regardless of direction.
    assert asc[-1] == null_id
    assert desc[-1] == null_id
    assert asc[:-1] == asc_ids
    assert desc[:-1] == desc_ids


def test_sort_hiring_rate_nulls_last_both_directions(api_env):
    with api_env.session() as s:
        c1 = make_client(s, _n=1, hiring_rate=20.0)
        c2 = make_client(s, _n=2, hiring_rate=50.0)
        c3 = make_client(s, _n=3, hiring_rate=90.0)
        cn = make_client(s, _n=4, hiring_rate=None)
        p1 = make_project(s, _n=1, client_id=c1.id)
        p2 = make_project(s, _n=2, client_id=c2.id)
        p3 = make_project(s, _n=3, client_id=c3.id)
        # A project whose sort-column (hiring_rate) is NULL: both null-rate client and
        # a client-less project qualify; use a client-less one to also exercise that path.
        pnull_rate = make_project(s, _n=4, client_id=cn.id)
        pclientless = make_project(s, _n=5, client_id=None)
        s.commit()
        order_low_to_high = [p1.id, p2.id, p3.id]
        null_ids = {pnull_rate.id, pclientless.id}
    c = api_env.client()
    asc = _ids(_get(c, sort="hiring_rate", order="asc")["items"])
    desc = _ids(_get(c, sort="hiring_rate", order="desc")["items"])

    # Non-null hiring rates ordered correctly, nulls trailing in both directions.
    assert asc[:3] == order_low_to_high
    assert desc[:3] == list(reversed(order_low_to_high))
    assert set(asc[3:]) == null_ids
    assert set(desc[3:]) == null_ids


def test_sort_default_is_posted_at_desc(api_env):
    now = _now()
    with api_env.session() as s:
        oldest = make_project(s, _n=1, posted_at=now - timedelta(hours=5))
        mid = make_project(s, _n=2, posted_at=now - timedelta(hours=2))
        newest = make_project(s, _n=3, posted_at=now)
        s.commit()
        oldest_id, mid_id, newest_id = oldest.id, mid.id, newest.id
    c = api_env.client()
    assert _ids(_get(c)["items"]) == [newest_id, mid_id, oldest_id]


@pytest.mark.parametrize("param,bad", [("sort", "bad"), ("order", "bad")])
def test_sort_order_invalid_422(api_env, param, bad):
    c = api_env.client()
    assert c.get("/api/projects", params={param: bad}).status_code == 422


# --------------------------------------------------------------------------- #
# Pagination
# --------------------------------------------------------------------------- #

def test_pagination_slices_and_stable_total(api_env):
    now = _now()
    with api_env.session() as s:
        # Seed 5 with strictly decreasing posted_at so default desc order is deterministic.
        ordered = []
        for i in range(5):
            p = make_project(s, _n=i + 1, posted_at=now - timedelta(hours=i))
            ordered.append(p.id)  # ordered[0] newest
        s.commit()
    c = api_env.client()
    p1 = _get(c, page=1, page_size=2)
    p2 = _get(c, page=2, page_size=2)
    p3 = _get(c, page=3, page_size=2)

    assert p1["total"] == 5 and p2["total"] == 5 and p3["total"] == 5
    assert p1["page"] == 1 and p1["page_size"] == 2
    assert _ids(p1["items"]) == ordered[0:2]
    assert _ids(p2["items"]) == ordered[2:4]
    assert _ids(p3["items"]) == ordered[4:5]
    assert len(p3["items"]) == 1


def test_pagination_beyond_last_page_empty_items_total_stable(api_env):
    with api_env.session() as s:
        for i in range(5):
            make_project(s, _n=i + 1)
        s.commit()
    c = api_env.client()
    body = _get(c, page=99, page_size=2)
    assert body["items"] == []
    assert body["total"] == 5
    assert body["page"] == 99


def test_total_independent_of_page(api_env):
    with api_env.session() as s:
        for i in range(7):
            make_project(s, _n=i + 1)
        s.commit()
    c = api_env.client()
    assert _get(c, page=1, page_size=3)["total"] == 7
    assert _get(c, page=2, page_size=3)["total"] == 7


@pytest.mark.parametrize("params", [
    {"page_size": 0},
    {"page_size": 101},
    {"page": 0},
    {"page": -1},
])
def test_pagination_out_of_range_422(api_env, params):
    c = api_env.client()
    assert c.get("/api/projects", params=params).status_code == 422


def test_pagination_boundaries_valid(api_env):
    with api_env.session() as s:
        make_project(s, _n=1)
        s.commit()
    c = api_env.client()
    # page_size 1 and 100 are both valid.
    assert c.get("/api/projects", params={"page_size": 1}).status_code == 200
    assert c.get("/api/projects", params={"page_size": 100}).status_code == 200


# --------------------------------------------------------------------------- #
# AND-combination
# --------------------------------------------------------------------------- #

def test_filters_are_and_combined(api_env):
    now = _now()
    with api_env.session() as s:
        good_client = make_client(s, _n=1, hiring_rate=80.0)
        low_client = make_client(s, _n=2, hiring_rate=10.0)

        # The one row matching ALL conditions:
        #   tier=1, budget_max in [200,800], hiring_rate>=50, bids in [2,20],
        #   posted within 24h, site open, qualified, q="python"
        match = make_project(
            s, _n=1, tier=1, budget_max=500, client_id=good_client.id, bids_count=5,
            posted_at=now - timedelta(hours=2), site_status=ProjectStatus.open,
            eval_status=EvalStatus.qualified, title="python project", skills=["python"],
        )
        # Each of the following fails exactly one condition:
        wrong_tier = make_project(
            s, _n=2, tier=2, budget_max=500, client_id=good_client.id, bids_count=5,
            posted_at=now - timedelta(hours=2), site_status=ProjectStatus.open,
            eval_status=EvalStatus.qualified, title="python project", skills=["python"],
        )
        low_budget = make_project(
            s, _n=3, tier=1, budget_max=100, client_id=good_client.id, bids_count=5,
            posted_at=now - timedelta(hours=2), site_status=ProjectStatus.open,
            eval_status=EvalStatus.qualified, title="python project", skills=["python"],
        )
        low_rate = make_project(
            s, _n=4, tier=1, budget_max=500, client_id=low_client.id, bids_count=5,
            posted_at=now - timedelta(hours=2), site_status=ProjectStatus.open,
            eval_status=EvalStatus.qualified, title="python project", skills=["python"],
        )
        too_many_bids = make_project(
            s, _n=5, tier=1, budget_max=500, client_id=good_client.id, bids_count=99,
            posted_at=now - timedelta(hours=2), site_status=ProjectStatus.open,
            eval_status=EvalStatus.qualified, title="python project", skills=["python"],
        )
        too_old = make_project(
            s, _n=6, tier=1, budget_max=500, client_id=good_client.id, bids_count=5,
            posted_at=now - timedelta(hours=72), site_status=ProjectStatus.open,
            eval_status=EvalStatus.qualified, title="python project", skills=["python"],
        )
        wrong_status = make_project(
            s, _n=7, tier=1, budget_max=500, client_id=good_client.id, bids_count=5,
            posted_at=now - timedelta(hours=2), site_status=ProjectStatus.closed,
            eval_status=EvalStatus.qualified, title="python project", skills=["python"],
        )
        not_qualified = make_project(
            s, _n=8, tier=1, budget_max=500, client_id=good_client.id, bids_count=5,
            posted_at=now - timedelta(hours=2), site_status=ProjectStatus.open,
            eval_status=EvalStatus.disqualified, title="python project", skills=["python"],
        )
        no_q_match = make_project(
            s, _n=9, tier=1, budget_max=500, client_id=good_client.id, bids_count=5,
            posted_at=now - timedelta(hours=2), site_status=ProjectStatus.open,
            eval_status=EvalStatus.qualified, title="ruby project", skills=["ruby"],
        )
        s.commit()
        match_id = match.id
        fail_ids = {
            wrong_tier.id, low_budget.id, low_rate.id, too_many_bids.id, too_old.id,
            wrong_status.id, not_qualified.id, no_q_match.id,
        }
    c = api_env.client()
    out = _idset(_get(
        c,
        tier=1, budget_min=200, budget_max=800, min_hiring_rate=50,
        bids_min=2, bids_max=20, posted_within_hours=24, site_status="open",
        qualified_only=True, q="python",
    )["items"])
    assert out == {match_id}
    assert out.isdisjoint(fail_ids)


# --------------------------------------------------------------------------- #
# Item shape
# --------------------------------------------------------------------------- #

EXPECTED_KEYS = {
    "id", "title", "url", "client_name", "client_hiring_rate", "budget_min",
    "budget_max", "currency", "tier", "tier_label", "bids_count", "posted_at",
    "site_status", "eval_status", "qualified",
    # Feature 3 — personal projection (defaulted when no record exists).
    "favorite", "personal_status", "personal_status_label", "tags", "hidden",
    # Feature 4 — opportunity score + freshness signal (null for unscored projects).
    "score", "freshness",
}


def test_item_shape_with_client(api_env):
    now = _now()
    with api_env.session() as s:
        cl = make_client(s, _n=1, name="ACME", hiring_rate=77.5)
        p = make_project(
            s, _n=1, title="T", url="https://x/1", budget_min=100, budget_max=500,
            currency="USD", tier=1, bids_count=4, posted_at=now,
            site_status=ProjectStatus.open, eval_status=EvalStatus.qualified, client_id=cl.id,
        )
        s.commit()
        pid = p.id
    c = api_env.client()
    item = next(it for it in _get(c)["items"] if it["id"] == pid)
    assert set(item.keys()) == EXPECTED_KEYS
    assert item["title"] == "T"
    assert item["url"] == "https://x/1"
    assert item["client_name"] == "ACME"
    assert item["client_hiring_rate"] == 77.5
    assert item["budget_min"] == 100.0
    assert item["budget_max"] == 500.0
    assert item["currency"] == "USD"
    assert item["tier"] == 1
    assert item["tier_label"] == "Tier 1"
    assert item["bids_count"] == 4
    assert item["site_status"] == "open"
    assert item["eval_status"] == "qualified"
    assert item["qualified"] is True


def test_item_tier2_label(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1, tier=2)
        s.commit()
        pid = p.id
    c = api_env.client()
    item = next(it for it in _get(c)["items"] if it["id"] == pid)
    assert item["tier"] == 2
    assert item["tier_label"] == "Tier 2"


def test_item_tier_null_label_null(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1, tier=None)
        s.commit()
        pid = p.id
    c = api_env.client()
    item = next(it for it in _get(c)["items"] if it["id"] == pid)
    assert item["tier"] is None
    assert item["tier_label"] is None


def test_item_shape_clientless_null_client_fields(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1, client_id=None, budget_min=None, budget_max=None)
        s.commit()
        pid = p.id
    c = api_env.client()
    item = next(it for it in _get(c)["items"] if it["id"] == pid)
    assert set(item.keys()) == EXPECTED_KEYS
    assert item["client_name"] is None
    assert item["client_hiring_rate"] is None
    # budget nulls stay null (never coerced to 0).
    assert item["budget_min"] is None
    assert item["budget_max"] is None


def test_clientless_project_appears_without_filters(api_env):
    with api_env.session() as s:
        withc = make_project(s, _n=1, client_id=make_client(s, _n=1).id)
        clientless = make_project(s, _n=2, client_id=None)
        s.commit()
        withc_id, clientless_id = withc.id, clientless.id
    c = api_env.client()
    assert _idset(_get(c)["items"]) == {withc_id, clientless_id}
