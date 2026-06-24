"""T013 — projects list: filters, sorting (NULLs last), pagination, AND-combination."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mostaql_notifier.db.models import EvalStatus, ProjectStatus
from tests.api.conftest import make_client, make_project


def _utc(dt: datetime | None = None) -> datetime:
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _ids(items) -> set[int]:
    return {it["id"] for it in items}


def test_tier_filter(api_env):
    with api_env.session() as s:
        a = make_project(s, _n=1, tier=1)
        b = make_project(s, _n=2, tier=2)
        s.commit()
        a_id, b_id = a.id, b.id

    client = api_env.client(auth_enabled=False)
    items = client.get("/api/projects", params={"tier": 2}).json()["items"]
    assert _ids(items) == {b_id}
    assert a_id not in _ids(items)


def test_budget_filter_on_budget_max(api_env):
    with api_env.session() as s:
        low = make_project(s, _n=1, budget_max=100)
        mid = make_project(s, _n=2, budget_max=500)
        high = make_project(s, _n=3, budget_max=1000)
        s.commit()
        low_id, mid_id, high_id = low.id, mid.id, high.id

    client = api_env.client(auth_enabled=False)
    items = client.get(
        "/api/projects", params={"budget_min": 200, "budget_max": 800}
    ).json()["items"]
    assert _ids(items) == {mid_id}
    assert low_id not in _ids(items)
    assert high_id not in _ids(items)


def test_min_hiring_rate_excludes_null_hiring_rate(api_env):
    with api_env.session() as s:
        high_c = make_client(s, _n=1, hiring_rate=90.0)
        none_c = make_client(s, _n=2, hiring_rate=None)
        low_c = make_client(s, _n=3, hiring_rate=20.0)
        keep = make_project(s, _n=1, client_id=high_c.id)
        excluded_null = make_project(s, _n=2, client_id=none_c.id)
        excluded_low = make_project(s, _n=3, client_id=low_c.id)
        s.commit()
        keep_id = keep.id
        null_id, low_id = excluded_null.id, excluded_low.id

    client = api_env.client(auth_enabled=False)
    items = client.get(
        "/api/projects", params={"min_hiring_rate": 50}
    ).json()["items"]
    assert _ids(items) == {keep_id}
    # A client whose hiring_rate is None (not-yet-calculated) is excluded.
    assert null_id not in _ids(items)
    assert low_id not in _ids(items)


def test_bids_range_filter(api_env):
    with api_env.session() as s:
        few = make_project(s, _n=1, bids_count=1)
        mid = make_project(s, _n=2, bids_count=5)
        many = make_project(s, _n=3, bids_count=20)
        s.commit()
        few_id, mid_id, many_id = few.id, mid.id, many.id

    client = api_env.client(auth_enabled=False)
    items = client.get(
        "/api/projects", params={"bids_min": 3, "bids_max": 10}
    ).json()["items"]
    assert _ids(items) == {mid_id}
    assert few_id not in _ids(items)
    assert many_id not in _ids(items)


def test_posted_within_hours_filter(api_env):
    with api_env.session() as s:
        recent = make_project(s, _n=1, posted_at=_utc() - timedelta(hours=1))
        old = make_project(s, _n=2, posted_at=_utc() - timedelta(hours=48))
        s.commit()
        recent_id, old_id = recent.id, old.id

    client = api_env.client(auth_enabled=False)
    items = client.get(
        "/api/projects", params={"posted_within_hours": 24}
    ).json()["items"]
    assert _ids(items) == {recent_id}
    assert old_id not in _ids(items)


def test_site_status_filter(api_env):
    with api_env.session() as s:
        op = make_project(s, _n=1, site_status=ProjectStatus.open)
        cl = make_project(s, _n=2, site_status=ProjectStatus.closed)
        s.commit()
        op_id, cl_id = op.id, cl.id

    client = api_env.client(auth_enabled=False)
    items = client.get(
        "/api/projects", params={"site_status": "closed"}
    ).json()["items"]
    assert _ids(items) == {cl_id}
    assert op_id not in _ids(items)


def test_qualified_only_filter(api_env):
    with api_env.session() as s:
        qualified = make_project(s, _n=1, eval_status=EvalStatus.qualified)
        pending = make_project(s, _n=2, eval_status=EvalStatus.pending)
        disq = make_project(s, _n=3, eval_status=EvalStatus.disqualified)
        s.commit()
        q_id, p_id, d_id = qualified.id, pending.id, disq.id

    client = api_env.client(auth_enabled=False)
    items = client.get(
        "/api/projects", params={"qualified_only": "true"}
    ).json()["items"]
    assert _ids(items) == {q_id}
    assert p_id not in _ids(items)
    assert d_id not in _ids(items)


def test_default_sort_is_posted_at_desc(api_env):
    with api_env.session() as s:
        oldest = make_project(s, _n=1, posted_at=_utc() - timedelta(hours=10))
        newest = make_project(s, _n=2, posted_at=_utc() - timedelta(hours=1))
        middle = make_project(s, _n=3, posted_at=_utc() - timedelta(hours=5))
        s.commit()
        order_expected = [newest.id, middle.id, oldest.id]

    client = api_env.client(auth_enabled=False)
    items = client.get("/api/projects").json()["items"]
    assert [it["id"] for it in items] == order_expected


def test_sort_by_budget_with_nulls_last(api_env):
    with api_env.session() as s:
        small = make_project(s, _n=1, budget_max=100)
        big = make_project(s, _n=2, budget_max=900)
        nul = make_project(s, _n=3, budget_max=None)
        s.commit()
        small_id, big_id, null_id = small.id, big.id, nul.id

    client = api_env.client(auth_enabled=False)
    items = client.get(
        "/api/projects", params={"sort": "budget", "order": "desc"}
    ).json()["items"]
    ordered = [it["id"] for it in items]
    # Highest budget first, NULL budget last regardless of order direction.
    assert ordered[0] == big_id
    assert ordered[1] == small_id
    assert ordered[-1] == null_id


def test_sort_by_bids_count_asc(api_env):
    with api_env.session() as s:
        a = make_project(s, _n=1, bids_count=8)
        b = make_project(s, _n=2, bids_count=2)
        c = make_project(s, _n=3, bids_count=None)
        s.commit()
        a_id, b_id, c_id = a.id, b.id, c.id

    client = api_env.client(auth_enabled=False)
    items = client.get(
        "/api/projects", params={"sort": "bids_count", "order": "asc"}
    ).json()["items"]
    ordered = [it["id"] for it in items]
    assert ordered[0] == b_id
    assert ordered[1] == a_id
    assert ordered[-1] == c_id  # NULL last


def test_sort_by_hiring_rate_with_nulls_last(api_env):
    with api_env.session() as s:
        high_c = make_client(s, _n=1, hiring_rate=95.0)
        low_c = make_client(s, _n=2, hiring_rate=10.0)
        none_c = make_client(s, _n=3, hiring_rate=None)
        high = make_project(s, _n=1, client_id=high_c.id)
        low = make_project(s, _n=2, client_id=low_c.id)
        nul = make_project(s, _n=3, client_id=none_c.id)
        s.commit()
        high_id, low_id, null_id = high.id, low.id, nul.id

    client = api_env.client(auth_enabled=False)
    items = client.get(
        "/api/projects", params={"sort": "hiring_rate", "order": "desc"}
    ).json()["items"]
    ordered = [it["id"] for it in items]
    assert ordered[0] == high_id
    assert ordered[1] == low_id
    assert ordered[-1] == null_id


def test_pagination(api_env):
    with api_env.session() as s:
        for i in range(1, 6):
            make_project(s, _n=i, posted_at=_utc() - timedelta(hours=i))
        s.commit()

    client = api_env.client(auth_enabled=False)
    body = client.get(
        "/api/projects", params={"page": 1, "page_size": 2}
    ).json()
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["items"]) == 2

    page3 = client.get(
        "/api/projects", params={"page": 3, "page_size": 2}
    ).json()
    assert len(page3["items"]) == 1  # 5th project on the last page


def test_page_size_cannot_exceed_100(api_env):
    client = api_env.client(auth_enabled=False)
    resp = client.get("/api/projects", params={"page_size": 101})
    assert resp.status_code == 422


def test_filters_combine_with_logical_and(api_env):
    with api_env.session() as s:
        good_client = make_client(s, _n=1, hiring_rate=90.0)
        bad_client = make_client(s, _n=2, hiring_rate=10.0)
        # Matches every condition.
        match = make_project(
            s, _n=1, tier=2, budget_max=600, bids_count=4,
            site_status=ProjectStatus.open, client_id=good_client.id,
        )
        # Fails tier.
        make_project(
            s, _n=2, tier=1, budget_max=600, bids_count=4,
            site_status=ProjectStatus.open, client_id=good_client.id,
        )
        # Fails hiring rate.
        make_project(
            s, _n=3, tier=2, budget_max=600, bids_count=4,
            site_status=ProjectStatus.open, client_id=bad_client.id,
        )
        # Fails budget.
        make_project(
            s, _n=4, tier=2, budget_max=100, bids_count=4,
            site_status=ProjectStatus.open, client_id=good_client.id,
        )
        s.commit()
        match_id = match.id

    client = api_env.client(auth_enabled=False)
    items = client.get(
        "/api/projects",
        params={
            "tier": 2,
            "budget_min": 300,
            "min_hiring_rate": 50,
            "bids_min": 2,
            "site_status": "open",
        },
    ).json()["items"]
    assert _ids(items) == {match_id}


def test_list_item_shape_and_detail_and_404(api_env):
    with api_env.session() as s:
        c = make_client(s, _n=1, name="عميل اختبار", hiring_rate=75.0)
        p = make_project(
            s, _n=1, title="مشروع", client_id=c.id, tier=2,
            skills=["python", "تصميم"],
        )
        sibling = make_project(s, _n=2, client_id=c.id)
        s.commit()
        p_id, sib_id = p.id, sibling.id

    client = api_env.client(auth_enabled=False)
    item = client.get("/api/projects").json()["items"][0]
    for field in (
        "id", "title", "url", "client_name", "client_hiring_rate",
        "budget_min", "budget_max", "currency", "tier", "tier_label",
        "bids_count", "posted_at", "site_status", "eval_status", "qualified",
    ):
        assert field in item

    detail = client.get(f"/api/projects/{p_id}").json()
    assert detail["id"] == p_id
    assert detail["description"] is not None
    assert detail["category"] is not None
    assert detail["skills"] == ["python", "تصميم"]
    assert detail["scraped_at"] is not None
    assert detail["client"]["name"] == "عميل اختبار"
    assert {sp["id"] for sp in detail["same_client_projects"]} == {sib_id}

    assert client.get("/api/projects/999999").status_code == 404
