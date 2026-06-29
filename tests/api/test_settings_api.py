"""T023 — settings read/write: registry projection and all-or-nothing validation."""
from __future__ import annotations

from mostaql_notifier.db.models import Setting

_EXPECTED_KEYS = {
    # original watcher tunables
    "poll_interval_seconds",
    "client_refresh_hours",
    "budget_primary_floor",
    "budget_fallback_floor",
    "fallback_target",
    "fallback_buffer",
    "fallback_window_hours",
    "min_hiring_rate",
    # Feature 4 — scoring weights
    "score_weight_hiring_rate",
    "score_weight_hire_volume",
    "score_weight_budget",
    "score_weight_competition",
    "score_weight_freshness",
    "score_weight_rating",
    # Feature 4 — scoring tuning
    "score_hiring_baseline",
    "score_hiring_shrink_k",
    "score_hire_volume_halfsat",
    "score_budget_cap_usd",
    "score_budget_tier2_scale",
    "score_competition_halfsat_bids",
    "score_competition_vel_cap",
    "score_freshness_halflife_hours",
    "score_rating_min_reviews",
    # Feature 4 — re-check loop
    "recheck_interval_seconds",
    "recheck_batch_size",
    "recheck_min_interval_seconds",
    "tracking_grace_hours",
    # Feature 4 — freshness thresholds
    "freshness_green_max_bids",
    "freshness_green_max_age_hours",
    "freshness_red_min_bids",
    "freshness_red_min_age_hours",
    # Feature 4 — Telegram default + toggles
    "top_default_count",
    "auto_status_site_enabled",
    "auto_status_personal_enabled",
}


def _stored_value(api_env, key: str) -> str:
    with api_env.session() as s:
        row = s.get(Setting, key)
        return row.value if row else None


def test_get_settings_returns_full_registry_with_metadata(api_env):
    client = api_env.client(auth_enabled=False)
    body = client.get("/api/settings").json()
    items = body["items"]
    assert len(items) == len(_EXPECTED_KEYS) == 34
    assert {it["key"] for it in items} == _EXPECTED_KEYS
    for it in items:
        for field in ("key", "value", "type", "min", "max", "label"):
            assert field in it
        assert it["type"] in ("int", "float", "bool")

    poll = next(it for it in items if it["key"] == "poll_interval_seconds")
    assert poll["type"] == "int"
    assert poll["min"] == 30

    rate = next(it for it in items if it["key"] == "min_hiring_rate")
    assert rate["type"] == "float"
    assert rate["min"] == 0
    assert rate["max"] == 100

    toggle = next(it for it in items if it["key"] == "auto_status_personal_enabled")
    assert toggle["type"] == "bool"
    assert toggle["value"] is False
    assert toggle["min"] is None and toggle["max"] is None


def test_valid_put_persists_to_settings_table(api_env):
    client = api_env.client(auth_enabled=False)
    resp = client.put("/api/settings", json={"budget_primary_floor": 300})
    assert resp.status_code == 200
    items = resp.json()["items"]
    floor = next(it for it in items if it["key"] == "budget_primary_floor")
    assert floor["value"] == 300

    # The settings table row the worker reads actually changed.
    assert _stored_value(api_env, "budget_primary_floor") == "300"

    # And a fresh GET reflects the change too.
    fresh = client.get("/api/settings").json()["items"]
    fresh_floor = next(it for it in fresh if it["key"] == "budget_primary_floor")
    assert fresh_floor["value"] == 300


def _assert_rejected_no_write(api_env, client, body, key_to_check):
    before = _stored_value(api_env, key_to_check)
    resp = client.put("/api/settings", json=body)
    assert resp.status_code == 422
    payload = resp.json()
    assert "detail" in payload
    assert isinstance(payload["errors"], list)
    assert payload["errors"]
    for err in payload["errors"]:
        assert "key" in err
        assert "message" in err
    # No write happened.
    assert _stored_value(api_env, key_to_check) == before


def test_put_unknown_key_rejected(api_env):
    client = api_env.client(auth_enabled=False)
    _assert_rejected_no_write(
        api_env, client,
        {"not_a_real_setting": 5},
        "budget_primary_floor",
    )


def test_put_wrong_type_rejected(api_env):
    client = api_env.client(auth_enabled=False)
    # A non-integer float for an int key.
    _assert_rejected_no_write(
        api_env, client,
        {"poll_interval_seconds": 30.5},
        "poll_interval_seconds",
    )


def test_put_below_minimum_rejected(api_env):
    client = api_env.client(auth_enabled=False)
    _assert_rejected_no_write(
        api_env, client,
        {"poll_interval_seconds": 10},
        "poll_interval_seconds",
    )


def test_put_hiring_rate_above_max_rejected(api_env):
    client = api_env.client(auth_enabled=False)
    _assert_rejected_no_write(
        api_env, client,
        {"min_hiring_rate": 150},
        "min_hiring_rate",
    )


def test_put_negative_floor_rejected(api_env):
    client = api_env.client(auth_enabled=False)
    _assert_rejected_no_write(
        api_env, client,
        {"budget_primary_floor": -5},
        "budget_primary_floor",
    )


def test_put_cross_field_fallback_exceeds_primary_rejected(api_env):
    client = api_env.client(auth_enabled=False)
    _assert_rejected_no_write(
        api_env, client,
        {"budget_fallback_floor": 999, "budget_primary_floor": 100},
        "budget_fallback_floor",
    )
