"""T043 (control half) — watcher pause/resume API: flip, idempotency, auth, home cross-check note."""
from __future__ import annotations


def test_control_default_is_not_paused(api_env):
    client = api_env.client(auth_enabled=False)
    assert client.get("/api/control").json() == {"paused": False}


def test_pause_then_resume_flips_flag(api_env):
    client = api_env.client(auth_enabled=False)
    assert client.post("/api/control/pause").json()["paused"] is True
    # A fresh request re-reads the persisted settings row.
    assert client.get("/api/control").json()["paused"] is True
    assert client.post("/api/control/resume").json()["paused"] is False
    assert client.get("/api/control").json()["paused"] is False


def test_pause_and_resume_are_idempotent(api_env):
    client = api_env.client(auth_enabled=False)
    client.post("/api/control/pause")
    assert client.post("/api/control/pause").json()["paused"] is True  # still paused, no error
    client.post("/api/control/resume")
    assert client.post("/api/control/resume").json()["paused"] is False  # still resumed


def test_control_requires_auth(api_env):
    client = api_env.client(auth_enabled=True, password="pw")
    assert client.get("/api/control").status_code == 401
    assert client.post("/api/control/pause").status_code == 401
    assert client.post("/api/control/resume").status_code == 401


def test_home_exposes_paused_field(api_env):
    # NOTE: wiring /api/home's `paused` to the watcher_paused flag is the integrator's job (home.py
    # is intentionally NOT edited here). After a pause, /api/control reflects it immediately; the
    # HomeOverview.paused field already exists in the schema and currently defaults to False until
    # home.py is wired — so we assert the field is present, not that it is True.
    client = api_env.client(auth_enabled=False)
    client.post("/api/control/pause")
    assert client.get("/api/control").json()["paused"] is True
    assert "paused" in client.get("/api/home").json()
