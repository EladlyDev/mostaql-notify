"""Exhaustive tests for GET /api/projects/{id} and ProjectDetail DTO serialization.

Focus areas:
- Happy path: full client + sibling projects, complete ProjectDetail shape.
- 404 for missing ids; 422 for non-integer path param.
- same_client_projects semantics (same client, excluding self; empty when client-less).
- Fail-closed null-safety: every nullable client numeric serializes as JSON null when None,
  never coerced to 0 / "" / missing. 0.0 / real 0 stays distinct from null.
- skills variants (list vs null).
"""
from __future__ import annotations

from tests.api.conftest import make_client, make_project

# ProjectListItem fields that must be present on the detail body and on each sibling.
LIST_ITEM_KEYS = {
    "id",
    "title",
    "url",
    "client_name",
    "client_hiring_rate",
    "budget_min",
    "budget_max",
    "currency",
    "tier",
    "tier_label",
    "bids_count",
    "posted_at",
    "site_status",
    "eval_status",
    "qualified",
}

# Extra fields ProjectDetail adds on top of ProjectListItem.
DETAIL_EXTRA_KEYS = {
    "description",
    "category",
    "skills",
    "scraped_at",
    "client",
    "same_client_projects",
}

# Nullable client numerics that must serialize as null (never 0) when the ORM value is None.
NULLABLE_CLIENT_NUMERICS = (
    "hiring_rate",
    "projects_posted",
    "projects_open",
    "hires_count",
    "avg_rating",
    "reviews_count",
    "total_spent",
)


def _assert_list_item_shape(item: dict) -> None:
    """Every ProjectListItem key is present (serializer is explicit, no missing fields)."""
    missing = LIST_ITEM_KEYS - item.keys()
    assert not missing, f"sibling/list item missing keys: {missing}"


# --------------------------------------------------------------------------- #
# 1. Happy path
# --------------------------------------------------------------------------- #


def test_happy_path_full_client_and_two_siblings(api_env):
    with api_env.session() as s:
        client = make_client(s, _n=1)
        p = make_project(
            s,
            _n=1,
            client_id=client.id,
            description="وصف تفصيلي",
            category="development",
            skills=["python", "برمجة"],
        )
        sib1 = make_project(s, _n=2, client_id=client.id)
        sib2 = make_project(s, _n=3, client_id=client.id)
        s.commit()
        pid, sib_ids = p.id, {sib1.id, sib2.id}

    resp = api_env.client().get(f"/api/projects/{pid}")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # All ProjectListItem fields + the detail extras are present.
    assert LIST_ITEM_KEYS <= body.keys()
    assert DETAIL_EXTRA_KEYS <= body.keys()

    # Detail-specific scalar fields.
    assert body["id"] == pid
    assert body["description"] == "وصف تفصيلي"
    assert body["category"] == "development"
    assert body["skills"] == ["python", "برمجة"]
    assert body["scraped_at"] is not None

    # Client panel fully populated, mirroring make_client defaults.
    c = body["client"]
    assert c is not None
    assert c["name"] == "عميل 1"
    assert c["hiring_rate"] == 80.0
    assert c["projects_posted"] == 5
    assert c["projects_open"] == 2
    assert c["hires_count"] == 3
    assert c["avg_rating"] == 4.5
    assert c["reviews_count"] == 10
    assert c["total_spent"] == 1000.0
    assert c["country"] == "مصر"
    assert c["member_since"] == "2020"
    assert c["verified"] is True

    # Siblings: exactly the two other same-client projects, NOT the requested one.
    sibs = body["same_client_projects"]
    assert len(sibs) == 2
    returned_ids = {item["id"] for item in sibs}
    assert returned_ids == sib_ids
    assert pid not in returned_ids
    for item in sibs:
        _assert_list_item_shape(item)


# --------------------------------------------------------------------------- #
# 2. 404 — missing id
# --------------------------------------------------------------------------- #


def test_missing_id_returns_404_with_detail(api_env):
    resp = api_env.client().get("/api/projects/999999")
    assert resp.status_code == 404
    body = resp.json()
    assert "detail" in body
    assert isinstance(body["detail"], str) and body["detail"]


# --------------------------------------------------------------------------- #
# 3. Bad path params
# --------------------------------------------------------------------------- #


def test_non_integer_id_returns_422(api_env):
    resp = api_env.client().get("/api/projects/abc")
    assert resp.status_code == 422


def test_negative_id_returns_404(api_env):
    # No path constraint forbids negatives, so it coerces fine and simply isn't found.
    resp = api_env.client().get("/api/projects/-1")
    assert resp.status_code == 404


def test_float_id_returns_422(api_env):
    resp = api_env.client().get("/api/projects/1.5")
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# 4. Client-less project
# --------------------------------------------------------------------------- #


def test_clientless_project_has_null_client_and_empty_siblings(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1, client_id=None)
        s.commit()
        pid = p.id

    resp = api_env.client().get(f"/api/projects/{pid}")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["client"] is None
    assert body["same_client_projects"] == []
    # Base client-derived fields are null, not empty/0.
    assert body["client_name"] is None
    assert body["client_hiring_rate"] is None


# --------------------------------------------------------------------------- #
# 5. Client with ALL-NULL optional fields — the critical fail-closed guarantee
# --------------------------------------------------------------------------- #


def test_all_null_client_fields_serialize_as_null_not_zero(api_env):
    with api_env.session() as s:
        client = make_client(
            s,
            _n=1,
            hiring_rate=None,
            projects_posted=None,
            projects_open=None,
            hires_count=None,
            avg_rating=None,
            reviews_count=None,
            total_spent=None,
            country=None,
            member_since=None,
        )
        p = make_project(s, _n=1, client_id=client.id)
        s.commit()
        pid = p.id

    resp = api_env.client().get(f"/api/projects/{pid}")
    assert resp.status_code == 200, resp.text
    c = resp.json()["client"]
    assert c is not None

    for field in NULLABLE_CLIENT_NUMERICS:
        assert field in c, f"client.{field} must be present, not missing"
        assert c[field] is None, f"client.{field} must be null, got {c[field]!r}"
        # Explicitly guard against the silent-zero / empty-string fail-open bug.
        assert c[field] != 0
        assert c[field] != 0.0
        assert c[field] != ""

    assert c["country"] is None
    assert c["member_since"] is None
    # client_hiring_rate also null on the base projection.
    assert resp.json()["client_hiring_rate"] is None


# --------------------------------------------------------------------------- #
# 6. hiring_rate 0.0 vs null distinction
# --------------------------------------------------------------------------- #


def test_hiring_rate_zero_and_null_are_distinct(api_env):
    with api_env.session() as s:
        c_zero = make_client(s, _n=1, hiring_rate=0.0)
        c_null = make_client(s, _n=2, hiring_rate=None)
        p_zero = make_project(s, _n=1, client_id=c_zero.id)
        p_null = make_project(s, _n=2, client_id=c_null.id)
        s.commit()
        zero_id, null_id = p_zero.id, p_null.id

    cl = api_env.client()

    body_zero = cl.get(f"/api/projects/{zero_id}").json()
    assert body_zero["client"]["hiring_rate"] == 0.0
    assert body_zero["client"]["hiring_rate"] is not None
    assert body_zero["client_hiring_rate"] == 0.0

    body_null = cl.get(f"/api/projects/{null_id}").json()
    assert body_null["client"]["hiring_rate"] is None
    assert body_null["client_hiring_rate"] is None


# --------------------------------------------------------------------------- #
# 7. Distinct-from-zero for a real 0 (total_spent)
# --------------------------------------------------------------------------- #


def test_total_spent_real_zero_vs_null(api_env):
    with api_env.session() as s:
        c_zero = make_client(s, _n=1, total_spent=0)
        c_null = make_client(s, _n=2, total_spent=None)
        p_zero = make_project(s, _n=1, client_id=c_zero.id)
        p_null = make_project(s, _n=2, client_id=c_null.id)
        s.commit()
        zero_id, null_id = p_zero.id, p_null.id

    cl = api_env.client()

    body_zero = cl.get(f"/api/projects/{zero_id}").json()
    assert body_zero["client"]["total_spent"] == 0
    assert body_zero["client"]["total_spent"] is not None

    body_null = cl.get(f"/api/projects/{null_id}").json()
    assert body_null["client"]["total_spent"] is None


# --------------------------------------------------------------------------- #
# 8. skills variants
# --------------------------------------------------------------------------- #


def test_skills_list_variant(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1, skills=["a", "ب"])
        s.commit()
        pid = p.id

    body = api_env.client().get(f"/api/projects/{pid}").json()
    assert body["skills"] == ["a", "ب"]


def test_skills_none_variant(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1, skills=None)
        s.commit()
        pid = p.id

    body = api_env.client().get(f"/api/projects/{pid}").json()
    # Source passes project.skills straight through; None -> null.
    assert body["skills"] is None


# --------------------------------------------------------------------------- #
# 9. Siblings exclude self & only same client
# --------------------------------------------------------------------------- #


def test_siblings_exclude_self_and_other_clients(api_env):
    with api_env.session() as s:
        client_a = make_client(s, _n=1)
        client_b = make_client(s, _n=2)
        p = make_project(s, _n=1, client_id=client_a.id)
        sib = make_project(s, _n=2, client_id=client_a.id)
        unrelated = make_project(s, _n=3, client_id=client_b.id)
        s.commit()
        pid, sib_id, unrelated_id = p.id, sib.id, unrelated.id

    body = api_env.client().get(f"/api/projects/{pid}").json()
    sib_ids = [item["id"] for item in body["same_client_projects"]]
    assert sib_ids == [sib_id]
    assert pid not in sib_ids
    assert unrelated_id not in sib_ids


# --------------------------------------------------------------------------- #
# 10. same_client empty when client has no other projects
# --------------------------------------------------------------------------- #


def test_lonely_client_has_empty_siblings(api_env):
    with api_env.session() as s:
        client = make_client(s, _n=1)
        p = make_project(s, _n=1, client_id=client.id)
        s.commit()
        pid = p.id

    body = api_env.client().get(f"/api/projects/{pid}").json()
    assert body["client"] is not None
    assert body["same_client_projects"] == []


# --------------------------------------------------------------------------- #
# Extra coverage: tier_label / budget passthrough on detail base fields.
# --------------------------------------------------------------------------- #


def test_tier_label_present_when_tier_set(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1, tier=2)
        s.commit()
        pid = p.id

    body = api_env.client().get(f"/api/projects/{pid}").json()
    assert body["tier"] == 2
    assert body["tier_label"] == "Tier 2"


def test_tier_label_null_when_tier_null(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1, tier=None)
        s.commit()
        pid = p.id

    body = api_env.client().get(f"/api/projects/{pid}").json()
    assert body["tier"] is None
    assert body["tier_label"] is None


def test_budget_nulls_stay_null(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1, budget_min=None, budget_max=None)
        s.commit()
        pid = p.id

    body = api_env.client().get(f"/api/projects/{pid}").json()
    assert body["budget_min"] is None
    assert body["budget_max"] is None


def test_sibling_inherits_client_fields_in_list_shape(api_env):
    """A sibling carries the same client_name/hiring_rate projection as a list item."""
    with api_env.session() as s:
        client = make_client(s, _n=1, hiring_rate=42.0)
        p = make_project(s, _n=1, client_id=client.id)
        make_project(s, _n=2, client_id=client.id)
        s.commit()
        pid = p.id

    body = api_env.client().get(f"/api/projects/{pid}").json()
    sib = body["same_client_projects"][0]
    assert sib["client_name"] == "عميل 1"
    assert sib["client_hiring_rate"] == 42.0
