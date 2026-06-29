"""T052 — scoring-model edge cases (contracts/scoring-model.md §2, §6).

Weight normalization extremes, the non-finite / NaN guard (→ component floor), the documented input
floors (unknown budget, missing bids), and the first-recheck velocity fallback vs the ≥2-snapshot
trajectory branch. All pure: ``SimpleNamespace`` stubs + a fixed ``now_utc``.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from mostaql_notifier.scoring import model

NOW = datetime(2026, 6, 28, 10, 0, 0, tzinfo=timezone.utc)


def _proj(**over):
    d = dict(
        budget_min=None,
        budget_max=Decimal("750"),
        currency="USD",
        tier=1,
        bids_count=6,
        posted_at=NOW - timedelta(hours=9),
        scraped_at=NOW - timedelta(hours=9),
        snapshots=[],
    )
    d.update(over)
    return SimpleNamespace(**d)


def _cli(**over):
    d = dict(hiring_rate=90.0, projects_posted=8, hires_count=12, avg_rating=4.5, reviews_count=6)
    d.update(over)
    return SimpleNamespace(**d)


def _snap(captured_at, bids):
    return SimpleNamespace(captured_at=captured_at, bids_count=bids)


def _score(project, client, settings):
    return model.score_project(project, client, settings=settings, now_utc=NOW)


def _sub(res, key):
    return {c["key"]: c for c in res.breakdown["components"]}[key]["sub_score"]


def _set_weights(settings, weights):
    settings.reload()
    for key, value in zip(model._WEIGHT_KEYS, weights, strict=True):
        settings._cache[key] = value


# --------------------------------------------------------------------------- §2 normalization edge


def test_weights_sum_not_one_is_flagged(settings):
    _set_weights(settings, [0.7, 0.3, 0.3, 0.4, 0.2, 0.1])  # W = 2.0
    res = _score(_proj(), _cli(), settings)
    assert res.breakdown["normalized"] is True
    assert res.breakdown["weights"]["sum"] == pytest.approx(2.0, abs=1e-9)
    assert sum(res.breakdown["weights"]["normalized"].values()) == pytest.approx(1.0, abs=1e-9)


def test_all_zero_weights_fall_back_to_equal(settings):
    _set_weights(settings, [0, 0, 0, 0, 0, 0])
    res = _score(_proj(), _cli(), settings)
    assert res.breakdown["normalized"] is True
    assert all(
        v == pytest.approx(1 / 6, abs=1e-6) for v in res.breakdown["weights"]["normalized"].values()
    )
    assert 0.0 <= res.score <= 100.0


# --------------------------------------------------------------------------- §2/§6 non-finite guards


def test_non_finite_hiring_rate_falls_to_floor(settings):
    res = _score(_proj(), _cli(hiring_rate=float("inf")), settings)
    assert _sub(res, "hiring_rate") == pytest.approx(0.5, abs=1e-9)  # baseline/100 floor
    assert math.isfinite(res.score) and 0.0 <= res.score <= 100.0


def test_nan_rating_falls_to_neutral(settings):
    res = _score(_proj(), _cli(avg_rating=float("nan"), reviews_count=10), settings)
    assert _sub(res, "rating") == pytest.approx(0.5, abs=1e-9)
    assert math.isfinite(res.score)


def test_inf_bids_competition_floor(settings):
    res = _score(_proj(bids_count=float("inf"), snapshots=[]), _cli(), settings)
    assert _sub(res, "competition") == pytest.approx(1.0, abs=1e-9)  # uncrowded floor
    assert math.isfinite(res.score)


def test_degenerate_settings_stay_bounded(settings):
    # zero denominators across components must not raise or go non-finite.
    settings.reload()
    settings._cache.update(
        {
            "score_hiring_shrink_k": 0,
            "score_hire_volume_halfsat": 0,
            "score_budget_cap_usd": 0,
            "score_competition_halfsat_bids": 0,
            "score_competition_vel_cap": 0.0,
            "score_freshness_halflife_hours": 0.0,
            "score_rating_min_reviews": 0,
        }
    )
    res = _score(_proj(bids_count=0, projects_posted=0), _cli(projects_posted=0), settings)
    assert math.isfinite(res.score) and 0.0 <= res.score <= 100.0
    for comp in res.breakdown["components"]:
        assert 0.0 <= comp["sub_score"] <= 1.0


# --------------------------------------------------------------------------- §6 input floors


def test_unknown_budget_floor(settings):
    res = _score(_proj(currency="JPY"), _cli(), settings)  # not in currency_usd_rates ⇒ None
    assert _sub(res, "budget") == pytest.approx(0.0, abs=1e-9)
    assert res.breakdown["inputs"]["budget_usd"] is None


def test_missing_bids_count_floor(settings):
    res = _score(_proj(bids_count=None, snapshots=[]), _cli(), settings)
    assert _sub(res, "competition") == pytest.approx(1.0, abs=1e-9)
    assert res.breakdown["inputs"]["bids_count"] == 0  # None ⇒ 0 echo


# --------------------------------------------------------------------------- §6 velocity branch


def test_velocity_first_recheck_fallback(settings):
    res = _score(_proj(bids_count=6, snapshots=[]), _cli(), settings)
    assert res.breakdown["inputs"]["velocity_source"] == "current_over_age"
    assert res.breakdown["inputs"]["velocity_bph"] == pytest.approx(6 / 9, abs=1e-4)


def test_velocity_one_snapshot_still_fallback(settings):
    res = _score(_proj(bids_count=6, snapshots=[_snap(NOW - timedelta(hours=2), 4)]), _cli(), settings)
    assert res.breakdown["inputs"]["velocity_source"] == "current_over_age"
    assert res.breakdown["inputs"]["snapshot_count"] == 1


def test_velocity_trajectory_branch(settings):
    snaps = [_snap(NOW - timedelta(hours=4), 4), _snap(NOW - timedelta(hours=2), 10)]
    res = _score(_proj(bids_count=10, snapshots=snaps), _cli(), settings)
    assert res.breakdown["inputs"]["velocity_source"] == "trajectory"
    # Δbids = 6 over Δhours = 2 ⇒ 3.0 bph
    assert res.breakdown["inputs"]["velocity_bph"] == pytest.approx(3.0, abs=1e-4)
    assert res.breakdown["inputs"]["snapshot_count"] == 2
