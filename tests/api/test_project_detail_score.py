"""T010 — project detail gains the Feature 4 scoring projection.

Covers: the detail body carries ``score``, ``outcome``, and a stored ``score_breakdown`` whose
``components`` each carry ``weight`` + ``contribution``, with the contributions summing to ~``score``
(FR-004/FR-007). The breakdown is seeded by the real pure scorer (via the scoring service) so the
test exercises the actual persisted shape, not a hand-rolled stub. An unscored project reads null.
"""
from __future__ import annotations

from datetime import datetime, timezone

from mostaql_notifier.config.settings_store import SettingsStore
from mostaql_notifier.db.models import EvalStatus, Outcome
from mostaql_notifier.scoring import service as scoring_service
from tests.api.conftest import make_client, make_project, make_project_score


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_detail_returns_score_outcome_and_breakdown_summing_to_score(api_env):
    with api_env.session() as s:
        client = make_client(
            s, _n=1, hiring_rate=90.0, projects_posted=20, hires_count=15,
            avg_rating=4.8, reviews_count=12,
        )
        p = make_project(
            s, _n=1, client_id=client.id, eval_status=EvalStatus.qualified,
            budget_max=800, bids_count=4,
        )
        # Score via the real scorer so the persisted breakdown is the genuine shape.
        row = scoring_service.score_project(s, p, settings=SettingsStore(s), now_utc=_now())
        s.commit()
        pid = p.id
        expected_score = row.score

    body = api_env.client().get(f"/api/projects/{pid}").json()

    # score flows through the list item; outcome defaults to "open" for a live score row.
    assert body["score"] == expected_score
    assert body["outcome"] == "open"

    bd = body["score_breakdown"]
    assert bd is not None
    # The breakdown stores the score rounded to 2 dp; the column keeps full precision.
    assert bd["score"] == round(expected_score, 2)
    assert isinstance(bd["normalized"], bool)
    assert len(bd["components"]) == 6  # the six weighted components

    total_contribution = 0.0
    for comp in bd["components"]:
        assert "weight" in comp and "contribution" in comp
        assert 0.0 <= comp["weight"] <= 1.0
        assert 0.0 <= comp["sub_score"] <= 1.0
        # contribution == 100 × weight × sub_score (to the stored 2-dp rounding).
        assert abs(comp["contribution"] - 100.0 * comp["weight"] * comp["sub_score"]) < 0.05
        total_contribution += comp["contribution"]

    # The total score equals the sum of the component contributions (within rounding).
    assert abs(total_contribution - bd["score"]) < 0.1
    # The six normalized weights sum to 1.
    assert abs(sum(c["weight"] for c in bd["components"]) - 1.0) < 1e-6


def test_detail_outcome_reflects_stored_value(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)
        make_project_score(s, project=p, score=64.0, outcome=Outcome.closed_no_hire)
        s.commit()
        pid = p.id

    body = api_env.client().get(f"/api/projects/{pid}").json()
    assert body["score"] == 64.0
    assert body["outcome"] == "closed_no_hire"


def test_detail_unscored_project_has_null_score_outcome_breakdown(api_env):
    with api_env.session() as s:
        p = make_project(s, _n=1)  # no score_row
        s.commit()
        pid = p.id

    body = api_env.client().get(f"/api/projects/{pid}").json()
    assert body["score"] is None
    assert body["freshness"] is None
    assert body["outcome"] is None
    assert body["score_breakdown"] is None
