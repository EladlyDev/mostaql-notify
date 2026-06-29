"""T011 — scoring-tunable settings: range validation + the re-score-on-change trigger.

Covers two contracts:

* The Feature 4 scoring weights / tuning numerics are validated against the registry min/max — an
  out-of-range value is refused with a per-field 422 and NOTHING is written; an in-range value
  persists to the ``settings`` table the worker reads.
* When a PUT changes any ``score_*`` key (a weight or tuning value), the server synchronously
  re-scores every qualified project from stored data BEFORE responding (SC-006), so the persisted
  ``project_scores.score`` reflects the new model. Loop / freshness / top / toggle keys do NOT.
"""
from __future__ import annotations

from datetime import datetime, timezone

from mostaql_notifier.config.settings_store import SettingsStore
from mostaql_notifier.db.models import EvalStatus, ProjectScore, Setting
from mostaql_notifier.scoring import service as scoring_service
from tests.api.conftest import make_client, make_project


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stored_raw(api_env, key: str) -> str | None:
    with api_env.session() as s:
        row = s.get(Setting, key)
        return row.value if row is not None else None


def _stored_score(api_env, project_id: int) -> float | None:
    with api_env.session() as s:
        row = s.get(ProjectScore, project_id)
        return row.score if row is not None else None


def _err_keys(resp_json) -> set:
    return {e["key"] for e in resp_json["errors"]}


# --------------------------------------------------------------------------- range validation


def test_weight_below_min_rejected_no_write(api_env):
    client = api_env.client()
    before = _stored_raw(api_env, "score_weight_hiring_rate")
    r = client.put("/api/settings", json={"score_weight_hiring_rate": -0.1})
    assert r.status_code == 422, r.text
    assert "score_weight_hiring_rate" in _err_keys(r.json())
    assert _stored_raw(api_env, "score_weight_hiring_rate") == before


def test_weight_any_nonnegative_float_accepted_not_required_to_sum_to_one(api_env):
    """FR-009 — a weight may be any non-negative float; the registry does NOT require sum==1."""
    client = api_env.client()
    # A large weight (so the six no longer sum to 1) is perfectly valid.
    r = client.put("/api/settings", json={"score_weight_hiring_rate": 5.0})
    assert r.status_code == 200, r.text
    items = {it["key"]: it for it in r.json()["items"]}
    assert items["score_weight_hiring_rate"]["value"] == 5.0
    assert _stored_raw(api_env, "score_weight_hiring_rate") == "5.0"


def test_tuning_above_max_rejected_no_write(api_env):
    client = api_env.client()
    # score_budget_tier2_scale is bounded 0..1.
    before = _stored_raw(api_env, "score_budget_tier2_scale")
    r = client.put("/api/settings", json={"score_budget_tier2_scale": 1.5})
    assert r.status_code == 422, r.text
    assert "score_budget_tier2_scale" in _err_keys(r.json())
    assert _stored_raw(api_env, "score_budget_tier2_scale") == before


def test_tuning_int_below_min_rejected_no_write(api_env):
    client = api_env.client()
    # score_hire_volume_halfsat must be >= 1.
    before = _stored_raw(api_env, "score_hire_volume_halfsat")
    r = client.put("/api/settings", json={"score_hire_volume_halfsat": 0})
    assert r.status_code == 422, r.text
    assert "score_hire_volume_halfsat" in _err_keys(r.json())
    assert _stored_raw(api_env, "score_hire_volume_halfsat") == before


def test_tuning_baseline_above_max_rejected(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json={"score_hiring_baseline": 150})
    assert r.status_code == 422, r.text
    assert "score_hiring_baseline" in _err_keys(r.json())


def test_valid_tuning_persists_to_settings_table(api_env):
    client = api_env.client()
    r = client.put("/api/settings", json={"score_budget_cap_usd": 2000})
    assert r.status_code == 200, r.text
    items = {it["key"]: it for it in r.json()["items"]}
    assert items["score_budget_cap_usd"]["value"] == 2000
    assert _stored_raw(api_env, "score_budget_cap_usd") == "2000"


# --------------------------------------------------------------------------- re-score on change


def _seed_qualified_project(api_env) -> int:
    with api_env.session() as s:
        c = make_client(
            s, _n=1, hiring_rate=90.0, projects_posted=20, hires_count=15,
            avg_rating=4.8, reviews_count=12,
        )
        p = make_project(
            s, _n=1, client_id=c.id, eval_status=EvalStatus.qualified,
            budget_max=800, bids_count=4,
        )
        s.commit()
        return p.id


def test_changing_a_weight_rescores_qualified_project(api_env):
    """Editing a ``score_weight_*`` triggers a synchronous re-score: the stored score changes."""
    pid = _seed_qualified_project(api_env)
    client = api_env.client()

    # Establish a baseline score with the default weights.
    with api_env.session() as s:
        store = SettingsStore(s)
        store.reload()
        baseline = scoring_service.rescore_all(s, settings=store, now_utc=_now())
        s.commit()
    assert baseline == 1
    score_before = _stored_score(api_env, pid)
    assert score_before is not None

    # Heavily up-weight freshness (a brand-new project's freshness sub-score is ~1.0, the highest of
    # the six), so the re-scored value must rise.
    r = client.put("/api/settings", json={"score_weight_freshness": 50.0})
    assert r.status_code == 200, r.text

    score_after = _stored_score(api_env, pid)
    assert score_after is not None
    assert score_after != score_before
    assert score_after > score_before


def test_changing_a_weight_scores_a_previously_unscored_project(api_env):
    """The re-score creates the score row even when the project had none yet."""
    pid = _seed_qualified_project(api_env)
    assert _stored_score(api_env, pid) is None  # never scored

    client = api_env.client()
    r = client.put("/api/settings", json={"score_weight_budget": 0.5})
    assert r.status_code == 200, r.text

    score = _stored_score(api_env, pid)
    assert score is not None
    assert 0.0 <= score <= 100.0


def test_non_scoring_key_does_not_trigger_rescore(api_env):
    """A loop/top/toggle key change must NOT score projects (it doesn't affect the model)."""
    pid = _seed_qualified_project(api_env)
    assert _stored_score(api_env, pid) is None

    client = api_env.client()
    r = client.put("/api/settings", json={"top_default_count": 7})
    assert r.status_code == 200, r.text

    # No score row was created — the PUT did not re-score.
    assert _stored_score(api_env, pid) is None
