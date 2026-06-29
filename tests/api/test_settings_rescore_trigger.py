"""Edge coverage for PUT /api/settings — the re-score-on-change trigger + value round-tripping.

Extends ``test_settings_scoring`` with: a ``score_*`` tuning change (not just a weight) that shifts a
seeded scored project's stored score; a non-score change that leaves an EXISTING score untouched; a
bool-typed setting round-tripping as a JSON bool; a weight accepting 0 and a large float; and a
negative weight being rejected with the registry's per-field 422.
"""
from __future__ import annotations

from datetime import datetime, timezone

from mostaql_notifier.config.settings_store import SettingsStore
from mostaql_notifier.db.models import EvalStatus, ProjectScore, Setting
from mostaql_notifier.scoring import service as scoring_service
from tests.api.conftest import make_client, make_project


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stored_score(api_env, pid: int) -> float | None:
    with api_env.session() as s:
        row = s.get(ProjectScore, pid)
        return row.score if row is not None else None


def _seed_scored_qualified(api_env) -> int:
    """Seed a qualified project and give it a baseline stored score with default settings."""
    with api_env.session() as s:
        c = make_client(
            s, _n=1, hiring_rate=88.0, projects_posted=18, hires_count=14,
            avg_rating=4.7, reviews_count=11,
        )
        p = make_project(
            s, _n=1, client_id=c.id, eval_status=EvalStatus.qualified,
            budget_max=700, bids_count=5,
        )
        store = SettingsStore(s)
        store.reload()
        scoring_service.score_project(s, p, settings=store, now_utc=_now())
        s.commit()
        return p.id


def test_changing_score_tuning_key_rescores_and_changes_stored_score(api_env):
    pid = _seed_scored_qualified(api_env)
    before = _stored_score(api_env, pid)
    assert before is not None

    # A budget cap change alters the budget sub-score for a $700 project -> the score must shift.
    r = api_env.client().put("/api/settings", json={"score_budget_cap_usd": 100})
    assert r.status_code == 200, r.text

    after = _stored_score(api_env, pid)
    assert after is not None
    assert after != before


def test_changing_non_score_key_leaves_existing_score_unchanged(api_env):
    pid = _seed_scored_qualified(api_env)
    before = _stored_score(api_env, pid)
    assert before is not None

    r = api_env.client().put("/api/settings", json={"recheck_batch_size": 9})
    assert r.status_code == 200, r.text

    assert _stored_score(api_env, pid) == before


def test_bool_setting_round_trips_as_json_bool(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json={"auto_status_personal_enabled": True})
    assert r.status_code == 200, r.text
    items = {it["key"]: it for it in r.json()["items"]}
    item = items["auto_status_personal_enabled"]
    assert item["value"] is True  # a real JSON bool, not 1
    assert item["type"] == "bool"

    # Flip it back to False and confirm it round-trips as a bool again.
    r = client.put("/api/settings", json={"auto_status_personal_enabled": False})
    item = {it["key"]: it for it in r.json()["items"]}["auto_status_personal_enabled"]
    assert item["value"] is False


def test_weight_accepts_zero_and_large_float(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json={"score_weight_rating": 0})
    assert r.status_code == 200, r.text
    items = {it["key"]: it for it in r.json()["items"]}
    assert items["score_weight_rating"]["value"] == 0.0

    r = client.put("/api/settings", json={"score_weight_rating": 1000000.5})
    assert r.status_code == 200, r.text
    items = {it["key"]: it for it in r.json()["items"]}
    assert items["score_weight_rating"]["value"] == 1000000.5


def test_negative_weight_rejected_with_field_422(api_env):
    client = api_env.client()
    before = None
    with api_env.session() as s:
        row = s.get(Setting, "score_weight_budget")
        before = row.value if row is not None else None

    r = client.put("/api/settings", json={"score_weight_budget": -2.0})
    assert r.status_code == 422, r.text
    assert {e["key"] for e in r.json()["errors"]} == {"score_weight_budget"}

    # All-or-nothing: nothing was written.
    with api_env.session() as s:
        row = s.get(Setting, "score_weight_budget")
        assert (row.value if row is not None else None) == before
