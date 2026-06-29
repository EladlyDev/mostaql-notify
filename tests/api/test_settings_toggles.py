"""T039 — the two ``bool`` auto-status toggles in the settings registry.

Covers: GET projects ``auto_status_site_enabled`` / ``auto_status_personal_enabled`` as
``type:"bool"`` items carrying real JSON booleans (not 1/0); a PUT of a boolean persists and
round-trips through both the response and the ``settings`` table the worker reads; a non-boolean
value for a bool key is refused (422); and a boolean for a numeric key is still refused (a bool is
an int subclass, never a valid number).
"""
from __future__ import annotations

from mostaql_notifier.config.settings_store import SettingsStore
from mostaql_notifier.db.models import Setting

_BOOL_KEYS = ("auto_status_site_enabled", "auto_status_personal_enabled")


def _items(client) -> dict:
    r = client.get("/api/settings")
    assert r.status_code == 200
    return {it["key"]: it for it in r.json()["items"]}


def _stored_raw(api_env, key: str) -> str | None:
    with api_env.session() as s:
        row = s.get(Setting, key)
        return row.value if row is not None else None


def _store_get_bool(api_env, key: str) -> bool:
    with api_env.session() as s:
        store = SettingsStore(s)
        store.reload()
        return store.get_bool(key)


def _err_keys(resp_json) -> set:
    return {e["key"] for e in resp_json["errors"]}


def test_get_returns_bool_toggles_with_boolean_values(api_env):
    client = api_env.client()
    items = _items(client)
    for key in _BOOL_KEYS:
        assert key in items, key
        it = items[key]
        assert it["type"] == "bool"
        # A genuine JSON boolean, never an int/1-0 (bool is an int subclass).
        assert isinstance(it["value"], bool)
        assert it["min"] is None and it["max"] is None
        assert isinstance(it["label"], str) and it["label"]
    # Seeded defaults: site enabled, personal disabled.
    assert items["auto_status_site_enabled"]["value"] is True
    assert items["auto_status_personal_enabled"]["value"] is False


def test_put_bool_persists_and_round_trips(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json={"auto_status_personal_enabled": True})
    assert r.status_code == 200, r.text
    # response reflects the new value as a JSON boolean
    items = {it["key"]: it for it in r.json()["items"]}
    assert items["auto_status_personal_enabled"]["value"] is True
    # fresh GET reflects it
    assert _items(client)["auto_status_personal_enabled"]["value"] is True
    # serialized to the settings table the worker reads
    assert _stored_raw(api_env, "auto_status_personal_enabled") == "true"
    assert _store_get_bool(api_env, "auto_status_personal_enabled") is True


def test_put_bool_false_persists(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json={"auto_status_site_enabled": False})
    assert r.status_code == 200, r.text
    assert _items(client)["auto_status_site_enabled"]["value"] is False
    assert _stored_raw(api_env, "auto_status_site_enabled") == "false"
    assert _store_get_bool(api_env, "auto_status_site_enabled") is False


def test_non_bool_value_for_bool_key_rejected_no_write(api_env):
    client = api_env.client()
    before = _stored_raw(api_env, "auto_status_personal_enabled")
    r = client.put("/api/settings", json={"auto_status_personal_enabled": 1})
    assert r.status_code == 422, r.text
    assert "auto_status_personal_enabled" in _err_keys(r.json())
    # untouched
    assert _stored_raw(api_env, "auto_status_personal_enabled") == before


def test_string_value_for_bool_key_rejected(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json={"auto_status_site_enabled": "true"})
    assert r.status_code == 422, r.text
    assert "auto_status_site_enabled" in _err_keys(r.json())


def test_bool_value_for_numeric_key_rejected(api_env):
    client = api_env.client()
    before = _stored_raw(api_env, "poll_interval_seconds")
    r = client.put("/api/settings", json={"poll_interval_seconds": True})
    assert r.status_code == 422, r.text
    assert "poll_interval_seconds" in _err_keys(r.json())
    assert _stored_raw(api_env, "poll_interval_seconds") == before
