"""Exhaustive tests for GET/PUT /api/settings and the validate_updates registry.

Covers the HTTP layer (via TestClient) and the pure ``validate_updates`` unit where it
sharpens edge cases. Persistence is verified by reading the ``settings`` table back and by
confirming ``SettingsStore`` (what the worker reads) returns the new typed value.
"""
from __future__ import annotations

import pytest

from mostaql_notifier.api.settings_spec import (
    EDITABLE_SETTINGS,
    SettingsValidationError,
    validate_updates,
)
from mostaql_notifier.config.settings_store import SettingsStore
from mostaql_notifier.db.models import Setting

# The editable keys in registry (display) order — the original 8 watcher tunables followed by the
# Feature 4 scoring / re-check loop / freshness / Telegram keys (must match EDITABLE_SETTINGS order).
REGISTRY_ORDER = [
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
]

# Default seeded values for the editable keys (from settings_store.DEFAULTS).
DEFAULTS = {
    "poll_interval_seconds": 120,
    "client_refresh_hours": 12,
    "budget_primary_floor": 250,
    "budget_fallback_floor": 100,
    "fallback_target": 10,
    "fallback_buffer": 2,
    "fallback_window_hours": 24,
    "min_hiring_rate": 0,
    "score_weight_hiring_rate": 0.35,
    "score_weight_hire_volume": 0.15,
    "score_weight_budget": 0.15,
    "score_weight_competition": 0.20,
    "score_weight_freshness": 0.10,
    "score_weight_rating": 0.05,
    "score_hiring_baseline": 50.0,
    "score_hiring_shrink_k": 5,
    "score_hire_volume_halfsat": 10,
    "score_budget_cap_usd": 1000,
    "score_budget_tier2_scale": 0.6,
    "score_competition_halfsat_bids": 15,
    "score_competition_vel_cap": 3.0,
    "score_freshness_halflife_hours": 12.0,
    "score_rating_min_reviews": 3,
    "recheck_interval_seconds": 1800,
    "recheck_batch_size": 20,
    "recheck_min_interval_seconds": 1500,
    "tracking_grace_hours": 72,
    "freshness_green_max_bids": 8,
    "freshness_green_max_age_hours": 12,
    "freshness_red_min_bids": 20,
    "freshness_red_min_age_hours": 48,
    "top_default_count": 5,
    "auto_status_site_enabled": True,
    "auto_status_personal_enabled": False,
}

TYPES = {
    "poll_interval_seconds": "int",
    "client_refresh_hours": "int",
    "budget_primary_floor": "int",
    "budget_fallback_floor": "int",
    "fallback_target": "int",
    "fallback_buffer": "int",
    "fallback_window_hours": "int",
    "min_hiring_rate": "float",
    "score_weight_hiring_rate": "float",
    "score_weight_hire_volume": "float",
    "score_weight_budget": "float",
    "score_weight_competition": "float",
    "score_weight_freshness": "float",
    "score_weight_rating": "float",
    "score_hiring_baseline": "float",
    "score_hiring_shrink_k": "int",
    "score_hire_volume_halfsat": "int",
    "score_budget_cap_usd": "int",
    "score_budget_tier2_scale": "float",
    "score_competition_halfsat_bids": "int",
    "score_competition_vel_cap": "float",
    "score_freshness_halflife_hours": "float",
    "score_rating_min_reviews": "int",
    "recheck_interval_seconds": "int",
    "recheck_batch_size": "int",
    "recheck_min_interval_seconds": "int",
    "tracking_grace_hours": "int",
    "freshness_green_max_bids": "int",
    "freshness_green_max_age_hours": "int",
    "freshness_red_min_bids": "int",
    "freshness_red_min_age_hours": "int",
    "top_default_count": "int",
    "auto_status_site_enabled": "bool",
    "auto_status_personal_enabled": "bool",
}


# --------------------------------------------------------------------------- helpers


def _stored_raw(api_env, key: str) -> str | None:
    """Return the literal ``settings.value`` string for ``key`` (None if no row)."""
    with api_env.session() as s:
        row = s.get(Setting, key)
        return row.value if row is not None else None


def _store_get_int(api_env, key: str) -> int:
    with api_env.session() as s:
        store = SettingsStore(s)
        store.reload()
        return store.get_int(key)


def _store_get_float(api_env, key: str) -> float:
    with api_env.session() as s:
        store = SettingsStore(s)
        store.reload()
        return store.get_float(key)


def _get_items(client) -> dict:
    r = client.get("/api/settings")
    assert r.status_code == 200
    return {it["key"]: it for it in r.json()["items"]}


def _err_keys(resp_json) -> set:
    return {e["key"] for e in resp_json["errors"]}


# --------------------------------------------------------------------------- 1. GET


def test_get_returns_full_registry_in_order(api_env):
    client = api_env.client()
    r = client.get("/api/settings")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == len(REGISTRY_ORDER) == 34
    assert [it["key"] for it in items] == REGISTRY_ORDER
    # registry order matches the spec tuple too
    assert [s.key for s in EDITABLE_SETTINGS] == REGISTRY_ORDER


def test_get_each_item_has_all_fields(api_env):
    client = api_env.client()
    for it in client.get("/api/settings").json()["items"]:
        for field in ("key", "value", "type", "min", "max", "label"):
            assert field in it, f"{it.get('key')} missing {field}"
        assert isinstance(it["label"], str) and it["label"]


def test_get_types_correct(api_env):
    client = api_env.client()
    items = _get_items(client)
    for key, t in TYPES.items():
        assert items[key]["type"] == t
    # SettingItem.value is typed ``int | float | str`` (int first), so an int-typed setting
    # serialises as a JSON integer (120, not 120.0) and min_hiring_rate as a float.
    assert items["poll_interval_seconds"]["value"] == 120
    assert isinstance(items["poll_interval_seconds"]["value"], int)
    assert not isinstance(items["poll_interval_seconds"]["value"], bool)
    assert items["poll_interval_seconds"]["type"] == "int"
    assert items["min_hiring_rate"]["type"] == "float"
    assert isinstance(items["min_hiring_rate"]["value"], float)


def test_get_values_equal_defaults(api_env):
    client = api_env.client()
    items = _get_items(client)
    for key, expected in DEFAULTS.items():
        assert items[key]["value"] == expected


def test_get_min_max_match_registry(api_env):
    client = api_env.client()
    items = _get_items(client)
    assert items["poll_interval_seconds"]["min"] == 30
    assert items["poll_interval_seconds"]["max"] is None
    assert items["client_refresh_hours"]["min"] == 1
    assert items["budget_primary_floor"]["min"] == 0
    assert items["budget_fallback_floor"]["min"] == 0
    assert items["fallback_window_hours"]["min"] == 1
    assert items["min_hiring_rate"]["min"] == 0
    assert items["min_hiring_rate"]["max"] == 100


# --------------------------------------------------------------------------- 2. Valid PUT persists


def test_put_single_valid_persists_everywhere(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json={"budget_primary_floor": 300})
    assert r.status_code == 200
    # response (GET payload) reflects 300
    items = {it["key"]: it for it in r.json()["items"]}
    assert items["budget_primary_floor"]["value"] == 300
    # fresh GET reflects 300
    assert _get_items(client)["budget_primary_floor"]["value"] == 300
    # settings table row literally changed
    assert _stored_raw(api_env, "budget_primary_floor") == "300"
    # worker read path
    assert _store_get_int(api_env, "budget_primary_floor") == 300


def test_put_multi_key_valid_updates_all(api_env):
    client = api_env.client()
    payload = {
        "poll_interval_seconds": 90,
        "client_refresh_hours": 6,
        "fallback_target": 25,
        "min_hiring_rate": 42.5,
    }
    r = client.put("/api/settings", json=payload)
    assert r.status_code == 200
    items = _get_items(client)
    assert items["poll_interval_seconds"]["value"] == 90
    assert items["client_refresh_hours"]["value"] == 6
    assert items["fallback_target"]["value"] == 25
    assert items["min_hiring_rate"]["value"] == 42.5
    assert _store_get_int(api_env, "poll_interval_seconds") == 90
    assert _store_get_float(api_env, "min_hiring_rate") == 42.5


# --------------------------------------------------------------------------- 3. Boundary acceptance


@pytest.mark.parametrize(
    "key,value",
    [
        ("poll_interval_seconds", 30),  # exact min
        ("client_refresh_hours", 1),
        ("budget_fallback_floor", 0),  # 0 <= primary(250) -> ok
        ("fallback_target", 0),
        ("fallback_buffer", 0),
        ("fallback_window_hours", 1),
        ("min_hiring_rate", 0),
        ("min_hiring_rate", 100),  # exact max
    ],
)
def test_boundary_accept(api_env, key, value):
    client = api_env.client()
    r = client.put("/api/settings", json={key: value})
    assert r.status_code == 200, r.text
    assert _get_items(client)[key]["value"] == value


def test_boundary_accept_budget_primary_floor_zero(api_env):
    """primary=0 (exact min) is only valid if fallback is also <= 0 (cross-field).

    Lower both floors to 0 in one all-or-nothing PUT so the merged state is consistent.
    """
    client = api_env.client()
    r = client.put(
        "/api/settings",
        json={"budget_primary_floor": 0, "budget_fallback_floor": 0},
    )
    assert r.status_code == 200, r.text
    items = _get_items(client)
    assert items["budget_primary_floor"]["value"] == 0
    assert items["budget_fallback_floor"]["value"] == 0


# --------------------------------------------------------------------------- 4. Boundary rejection (422 + no write)


@pytest.mark.parametrize(
    "key,value",
    [
        ("poll_interval_seconds", 29),
        ("client_refresh_hours", 0),
        ("budget_primary_floor", -1),
        ("budget_fallback_floor", -1),
        ("fallback_window_hours", 0),
        ("min_hiring_rate", -0.1),
        ("min_hiring_rate", 100.1),
    ],
)
def test_boundary_reject_no_write(api_env, key, value):
    client = api_env.client()
    before = _stored_raw(api_env, key)
    r = client.put("/api/settings", json={key: value})
    assert r.status_code == 422, r.text
    body = r.json()
    assert key in _err_keys(body)
    # nothing written
    assert _stored_raw(api_env, key) == before
    # GET unchanged
    assert _get_items(client)[key]["value"] == DEFAULTS[key]


# --------------------------------------------------------------------------- 5. Type rejection / coercion


def test_non_integer_float_for_int_key_rejected(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json={"poll_interval_seconds": 30.5})
    assert r.status_code == 422
    assert "poll_interval_seconds" in _err_keys(r.json())
    assert _stored_raw(api_env, "poll_interval_seconds") == "120"


def test_non_numeric_string_rejected(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json={"min_hiring_rate": "abc"})
    assert r.status_code == 422
    assert "min_hiring_rate" in _err_keys(r.json())


@pytest.mark.parametrize("key", ["poll_interval_seconds", "min_hiring_rate", "budget_primary_floor"])
def test_bool_value_rejected(api_env, key):
    client = api_env.client()
    before = _stored_raw(api_env, key)
    r = client.put("/api/settings", json={key: True})
    assert r.status_code == 422, r.text
    assert key in _err_keys(r.json())
    assert _stored_raw(api_env, key) == before


def test_null_value_rejected(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json={"poll_interval_seconds": None})
    assert r.status_code == 422
    assert "poll_interval_seconds" in _err_keys(r.json())
    assert _stored_raw(api_env, "poll_interval_seconds") == "120"


def test_integer_valued_float_accepted_as_int(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json={"poll_interval_seconds": 30.0})
    assert r.status_code == 200, r.text
    assert _get_items(client)["poll_interval_seconds"]["value"] == 30
    # stored as int "30", not "30.0"
    assert _stored_raw(api_env, "poll_interval_seconds") == "30"
    assert _store_get_int(api_env, "poll_interval_seconds") == 30


def test_int_for_float_key_accepted(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json={"min_hiring_rate": 80})
    assert r.status_code == 200, r.text
    assert _get_items(client)["min_hiring_rate"]["value"] == 80
    assert _store_get_float(api_env, "min_hiring_rate") == 80.0


# --------------------------------------------------------------------------- 6. Unknown / non-editable keys


def test_unknown_key_rejected(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json={"not_a_setting": 1})
    assert r.status_code == 422
    assert "not_a_setting" in _err_keys(r.json())


def test_real_but_non_editable_key_rejected(api_env):
    client = api_env.client()
    # owner_timezone is a real seeded setting but NOT in the editable registry
    before = _stored_raw(api_env, "owner_timezone")
    r = client.put("/api/settings", json={"owner_timezone": "X"})
    assert r.status_code == 422
    assert "owner_timezone" in _err_keys(r.json())
    # untouched
    assert _stored_raw(api_env, "owner_timezone") == before


# --------------------------------------------------------------------------- 7. Cross-field rule


def test_crossfield_fallback_exceeds_primary_in_payload_rejected(api_env):
    client = api_env.client()
    r = client.put(
        "/api/settings",
        json={"budget_fallback_floor": 300, "budget_primary_floor": 200},
    )
    assert r.status_code == 422
    assert "budget_fallback_floor" in _err_keys(r.json())
    # neither written
    assert _stored_raw(api_env, "budget_fallback_floor") == "100"
    assert _stored_raw(api_env, "budget_primary_floor") == "250"


def test_crossfield_equal_values_ok(api_env):
    client = api_env.client()
    r = client.put(
        "/api/settings",
        json={"budget_fallback_floor": 200, "budget_primary_floor": 200},
    )
    assert r.status_code == 200, r.text
    items = _get_items(client)
    assert items["budget_fallback_floor"]["value"] == 200
    assert items["budget_primary_floor"]["value"] == 200


def test_crossfield_single_key_against_current_reject(api_env):
    # primary currently 250; fallback=300 > 250 -> reject
    client = api_env.client()
    r = client.put("/api/settings", json={"budget_fallback_floor": 300})
    assert r.status_code == 422
    assert "budget_fallback_floor" in _err_keys(r.json())
    assert _stored_raw(api_env, "budget_fallback_floor") == "100"


def test_crossfield_single_key_against_current_ok(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json={"budget_fallback_floor": 200})
    assert r.status_code == 200, r.text
    assert _get_items(client)["budget_fallback_floor"]["value"] == 200


def test_crossfield_lowering_primary_below_current_fallback_rejected(api_env):
    """fallback=100 (default); lowering primary to 50 violates fallback<=primary -> 422.

    This is the case the prompt flags: the rule must be evaluated against the merged
    state (incoming primary over current fallback), not just within the payload.
    """
    client = api_env.client()
    r = client.put("/api/settings", json={"budget_primary_floor": 50})
    assert r.status_code == 422, (
        "Lowering primary (50) below current fallback (100) must be rejected; "
        f"got {r.status_code}: {r.text}"
    )
    assert "budget_fallback_floor" in _err_keys(r.json())
    # not written
    assert _stored_raw(api_env, "budget_primary_floor") == "250"


def test_crossfield_lowering_primary_to_exactly_fallback_ok(api_env):
    # fallback=100 default; primary=100 -> equal -> OK
    client = api_env.client()
    r = client.put("/api/settings", json={"budget_primary_floor": 100})
    assert r.status_code == 200, r.text
    assert _get_items(client)["budget_primary_floor"]["value"] == 100


# --------------------------------------------------------------------------- 8. All-or-nothing


def test_mixed_valid_invalid_writes_nothing(api_env):
    client = api_env.client()
    before_primary = _stored_raw(api_env, "budget_primary_floor")
    before_poll = _stored_raw(api_env, "poll_interval_seconds")
    r = client.put(
        "/api/settings",
        json={"budget_primary_floor": 300, "poll_interval_seconds": 5},
    )
    assert r.status_code == 422
    keys = _err_keys(r.json())
    assert "poll_interval_seconds" in keys
    # neither key written
    assert _stored_raw(api_env, "budget_primary_floor") == before_primary
    assert _stored_raw(api_env, "poll_interval_seconds") == before_poll
    assert _get_items(client)["budget_primary_floor"]["value"] == DEFAULTS["budget_primary_floor"]


# --------------------------------------------------------------------------- 9. Empty / non-dict bodies


def test_empty_body_ok_no_change(api_env):
    client = api_env.client()
    before = {k: _stored_raw(api_env, k) for k in REGISTRY_ORDER}
    r = client.put("/api/settings", json={})
    assert r.status_code == 200, r.text
    # documents behaviour: returns the full GET payload unchanged
    items = _get_items(client)
    for k in REGISTRY_ORDER:
        assert items[k]["value"] == DEFAULTS[k]
        assert _stored_raw(api_env, k) == before[k]


def test_non_dict_list_body_rejected(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json=[1, 2])
    assert r.status_code == 422


def test_non_dict_string_body_rejected(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json="hello")
    assert r.status_code == 422


# --------------------------------------------------------------------------- 10. validate_updates unit tests


def _current():
    return dict(DEFAULTS)


def test_unit_bool_rejected():
    with pytest.raises(SettingsValidationError) as ei:
        validate_updates({"poll_interval_seconds": True}, _current())
    assert any(k == "poll_interval_seconds" for k, _ in ei.value.errors)


def test_unit_integer_valued_float_coerced_to_int():
    out = validate_updates({"poll_interval_seconds": 30.0}, _current())
    assert out == {"poll_interval_seconds": 30}
    assert isinstance(out["poll_interval_seconds"], int)


def test_unit_non_integer_float_rejected():
    with pytest.raises(SettingsValidationError) as ei:
        validate_updates({"poll_interval_seconds": 30.5}, _current())
    assert any(k == "poll_interval_seconds" for k, _ in ei.value.errors)


def test_unit_numeric_string_for_int_accepted():
    # _coerce_typed does int("30") -> 30; a numeric string IS accepted by the registry.
    out = validate_updates({"poll_interval_seconds": "30"}, _current())
    assert out == {"poll_interval_seconds": 30}


def test_unit_non_integer_numeric_string_for_int_rejected():
    with pytest.raises(SettingsValidationError) as ei:
        validate_updates({"poll_interval_seconds": "30.5"}, _current())
    assert any(k == "poll_interval_seconds" for k, _ in ei.value.errors)


def test_unit_numeric_string_for_float_accepted():
    out = validate_updates({"min_hiring_rate": "42.5"}, _current())
    assert out == {"min_hiring_rate": 42.5}
    assert isinstance(out["min_hiring_rate"], float)


def test_unit_int_for_float_key_accepted():
    out = validate_updates({"min_hiring_rate": 80}, _current())
    assert out == {"min_hiring_rate": 80.0}
    assert isinstance(out["min_hiring_rate"], float)


def test_unit_multiple_errors_aggregated():
    updates = {
        "poll_interval_seconds": 5,  # below min
        "min_hiring_rate": "abc",  # non-numeric
        "not_a_setting": 1,  # unknown
    }
    with pytest.raises(SettingsValidationError) as ei:
        validate_updates(updates, _current())
    err_keys = {k for k, _ in ei.value.errors}
    assert {"poll_interval_seconds", "min_hiring_rate", "not_a_setting"} <= err_keys
    assert len(ei.value.errors) >= 3


def test_unit_valid_returns_only_coerced_no_exception():
    out = validate_updates({"fallback_target": 7}, _current())
    assert out == {"fallback_target": 7}


def test_unit_crossfield_lowering_primary_below_current_fallback():
    # current fallback=100, primary -> 50 ; 100 > 50 -> error
    with pytest.raises(SettingsValidationError) as ei:
        validate_updates({"budget_primary_floor": 50}, _current())
    assert any(k == "budget_fallback_floor" for k, _ in ei.value.errors)


def test_unit_crossfield_equal_ok():
    out = validate_updates(
        {"budget_fallback_floor": 200, "budget_primary_floor": 200}, _current()
    )
    assert out == {"budget_fallback_floor": 200, "budget_primary_floor": 200}


def test_unit_unknown_key_message_present():
    with pytest.raises(SettingsValidationError) as ei:
        validate_updates({"owner_timezone": "X"}, _current())
    keys = {k for k, _ in ei.value.errors}
    assert "owner_timezone" in keys
