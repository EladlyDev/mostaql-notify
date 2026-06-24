"""Targeted tests closing the last coverage gaps: app lifespan startup and the
settings INSERT-new-row branch (the seed-then-delete path)."""
from __future__ import annotations

from mostaql_notifier.config.settings_store import SettingsStore
from mostaql_notifier.db.models import Setting


def test_lifespan_startup_touches_engine(api_env):
    """Using the TestClient as a context manager runs the lifespan (WAL engine touch)."""
    client = api_env.client(auth_enabled=False)
    with client:  # enters lifespan → _lifespan calls get_engine()
        resp = client.get("/api/home")
        assert resp.status_code == 200


def test_put_inserts_missing_setting_row(api_env):
    """If a setting row is absent, PUT must INSERT it (not only update existing rows)."""
    # Remove the seeded row so the PUT hits the insert branch.
    with api_env.session() as s:
        row = s.get(Setting, "fallback_buffer")
        assert row is not None
        s.delete(row)
        s.commit()
    with api_env.session() as s:
        assert s.get(Setting, "fallback_buffer") is None

    client = api_env.client(auth_enabled=False)
    resp = client.put("/api/settings", json={"fallback_buffer": 7})
    assert resp.status_code == 200

    with api_env.session() as s:
        row = s.get(Setting, "fallback_buffer")
        assert row is not None and row.value == "7" and row.value_type == "int"
        store = SettingsStore(s)
        store.reload()
        assert store.get_int("fallback_buffer") == 7
