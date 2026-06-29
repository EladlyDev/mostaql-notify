"""T007 — pure scoring-model unit tests (contracts/scoring-model.md §2, §3, §4).

Lightweight ``SimpleNamespace`` stubs stand in for ``project`` / ``client`` / ``snapshot``; ``now_utc``
is injected fixed, so every assertion is deterministic. Settings come from the seeded ``settings``
fixture (the documented defaults).
"""
from __future__ import annotations

import json
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


def _components(result):
    return {c["key"]: c for c in result.breakdown["components"]}


def _sub(result, key):
    return _components(result)[key]["sub_score"]


def _score(project, client, settings):
    return model.score_project(project, client, settings=settings, now_utc=NOW)


# --------------------------------------------------------------------------- (a) hiring rate


def test_hiring_rate_shrinkage(settings):
    low_n = _sub(_score(_proj(), _cli(hiring_rate=90.0, projects_posted=8), settings), "hiring_rate")
    high_n = _sub(_score(_proj(), _cli(hiring_rate=90.0, projects_posted=40), settings), "hiring_rate")
    assert low_n == pytest.approx(0.7462, abs=1e-3)   # (90·8 + 50·5)/13 / 100
    assert high_n == pytest.approx(0.8556, abs=1e-3)  # more sample ⇒ less shrinkage
    assert high_n > low_n


def test_hiring_rate_none_is_neutral(settings):
    sub = _sub(_score(_proj(), _cli(hiring_rate=None, projects_posted=None), settings), "hiring_rate")
    assert sub == pytest.approx(0.5, abs=1e-9)  # r=b, n=0 ⇒ r_adj=b ⇒ b/100


# --------------------------------------------------------------------------- (b) hire volume


def test_hire_volume_halfsat_and_floor(settings):
    half = _sub(_score(_proj(), _cli(hires_count=10), settings), "hire_volume")  # h == s
    none = _sub(_score(_proj(), _cli(hires_count=None), settings), "hire_volume")
    assert half == pytest.approx(0.5, abs=1e-9)
    assert none == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------------------- (c) budget


def test_budget_cap_clamp_and_tier2(settings):
    capped = _sub(_score(_proj(budget_max=Decimal("1500"), tier=1), _cli(), settings), "budget")
    tier2 = _sub(_score(_proj(budget_max=Decimal("750"), tier=2), _cli(), settings), "budget")
    assert capped == pytest.approx(1.0, abs=1e-9)        # min(1500,1000)/1000
    assert tier2 == pytest.approx(0.75 * 0.6, abs=1e-9)  # cap clamp before the Tier-2 scale


def test_budget_unknown_currency_floor(settings):
    res = _score(_proj(currency="EUR"), _cli(), settings)  # not in currency_usd_rates ⇒ None
    assert _sub(res, "budget") == pytest.approx(0.0, abs=1e-9)
    assert _components(res)["budget"]["raw"] is None
    assert res.breakdown["inputs"]["budget_usd"] is None


# --------------------------------------------------------------------------- (d) competition


def test_competition_first_check_fallback(settings):
    res = _score(_proj(bids_count=6, snapshots=[]), _cli(), settings)
    assert _sub(res, "competition") == pytest.approx(0.7460, abs=1e-3)
    assert res.breakdown["inputs"]["velocity_source"] == "current_over_age"
    assert res.breakdown["inputs"]["velocity_bph"] == pytest.approx(6 / 9, abs=1e-3)


def test_competition_trajectory_climbing_drops(settings):
    snaps = [_snap(NOW - timedelta(hours=3), 5), _snap(NOW - timedelta(hours=1), 12)]
    res = _score(_proj(bids_count=12, snapshots=snaps), _cli(), settings)
    # crowd = 1 − 12/27 = 0.5556 ; v = (12−5)/2 = 3.5 ⇒ vel = 0 ; sub = 0.2778
    assert _sub(res, "competition") == pytest.approx(0.2778, abs=1e-3)
    assert res.breakdown["inputs"]["velocity_source"] == "trajectory"
    assert res.breakdown["inputs"]["velocity_bph"] == pytest.approx(3.5, abs=1e-3)


def test_competition_missing_bids_is_uncrowded(settings):
    res = _score(_proj(bids_count=None, snapshots=[]), _cli(), settings)
    assert _sub(res, "competition") == pytest.approx(1.0, abs=1e-9)


# --------------------------------------------------------------------------- (e) freshness


def test_freshness_halflife(settings):
    at_h = _sub(_score(_proj(posted_at=NOW - timedelta(hours=12)), _cli(), settings), "freshness")
    assert at_h == pytest.approx(0.5, abs=1e-9)  # age == half-life ⇒ 0.5


def test_freshness_falls_back_to_scraped_at(settings):
    res = _score(_proj(posted_at=None, scraped_at=NOW - timedelta(hours=9)), _cli(), settings)
    assert _sub(res, "freshness") == pytest.approx(0.5 ** 0.75, abs=1e-4)
    assert res.breakdown["inputs"]["age_hours"] == pytest.approx(9.0, abs=1e-6)


# --------------------------------------------------------------------------- (f) rating


def test_rating_full_confidence_swing(settings):
    hi = _sub(_score(_proj(), _cli(avg_rating=5.0, reviews_count=10), settings), "rating")
    lo = _sub(_score(_proj(), _cli(avg_rating=1.0, reviews_count=10), settings), "rating")
    assert hi == pytest.approx(1.0, abs=1e-9)  # +0.5 swing
    assert lo == pytest.approx(0.0, abs=1e-9)  # −0.5 swing


def test_rating_low_reviews_near_neutral(settings):
    sub = _sub(_score(_proj(), _cli(avg_rating=5.0, reviews_count=1), settings), "rating")
    assert sub == pytest.approx(0.5 + 1.0 * (1 / 3) * 0.5, abs=1e-3)  # ≈0.667, damped
    none = _sub(_score(_proj(), _cli(avg_rating=None, reviews_count=None), settings), "rating")
    assert none == pytest.approx(0.5, abs=1e-9)


# --------------------------------------------------------------------------- §2 normalization


def _set_weights(settings, weights):
    settings.reload()
    for key, value in zip(model._WEIGHT_KEYS, weights, strict=True):
        settings._cache[key] = value


def test_normalization_defaults_not_flagged(settings):
    res = _score(_proj(), _cli(), settings)
    assert res.breakdown["normalized"] is False
    assert res.breakdown["weights"]["sum"] == pytest.approx(1.0, abs=1e-9)


def test_normalization_scale_invariant(settings):
    base = _score(_proj(), _cli(), settings).score
    _set_weights(settings, [0.70, 0.30, 0.30, 0.40, 0.20, 0.10])  # defaults × 2
    doubled = _score(_proj(), _cli(), settings)
    assert doubled.score == pytest.approx(base, abs=1e-6)  # only ratios matter
    assert doubled.breakdown["normalized"] is True


def test_normalization_all_zero_equal_fallback(settings):
    _set_weights(settings, [0, 0, 0, 0, 0, 0])
    res = _score(_proj(), _cli(), settings)
    assert res.breakdown["normalized"] is True
    for value in res.breakdown["weights"]["normalized"].values():
        assert value == pytest.approx(1 / 6, abs=1e-6)
    # stored weights are rounded to 6 dp for display, so the sum is 1.0 within rounding.
    assert sum(res.breakdown["weights"]["normalized"].values()) == pytest.approx(1.0, abs=1e-5)


def test_normalization_arbitrary_sums_to_one(settings):
    _set_weights(settings, [0.5, 0, 0, 0.5, 0, 0])
    res = _score(_proj(), _cli(), settings)
    assert sum(res.breakdown["weights"]["normalized"].values()) == pytest.approx(1.0, abs=1e-9)
    assert res.breakdown["normalized"] is False  # W == 1.0


# --------------------------------------------------------------------------- §4 breakdown shape


def test_breakdown_completeness(settings):
    res = _score(_proj(snapshots=[_snap(NOW - timedelta(hours=9), 6)]), _cli(), settings)
    bd = res.breakdown

    assert len(bd["components"]) == 6
    fields = {"key", "label", "raw", "sub_score", "weight", "contribution"}
    for comp in bd["components"]:
        assert fields <= set(comp)
        assert 0.0 <= comp["sub_score"] <= 1.0
    # Arabic labels in the documented order.
    assert [c["label"] for c in bd["components"]] == [
        "معدل التوظيف", "حجم التوظيف", "الميزانية", "المنافسة", "الحداثة", "تقييم العميل",
    ]
    # bars add up to the total (within rounding), score bounded, computed_at echoed.
    total = sum(c["contribution"] for c in bd["components"])
    assert total == pytest.approx(bd["score"], abs=0.05)
    assert 0.0 <= res.score <= 100.0
    assert bd["computed_at"] == "2026-06-28T10:00:00Z"
    assert {"configured", "sum", "normalized"} <= set(bd["weights"])
    assert "inputs" in bd
    # JSON-serializable verbatim.
    json.dumps(bd)


def test_worked_example_reproduces_70_80(settings):
    """The §4 worked example: client r=90,n=8,h=12,rating=4.5,reviews=6; project budget 750 tier1,
    bids=6, posted 9 h ago, first re-check (one snapshot). Default weights ⇒ score ≈ 70.80."""
    project = _proj(snapshots=[_snap(NOW - timedelta(hours=9), 6)])
    res = _score(project, _cli(), settings)

    assert res.score == pytest.approx(70.80, abs=0.05)
    comps = _components(res)
    assert comps["hiring_rate"]["contribution"] == pytest.approx(26.12, abs=0.01)
    assert comps["hire_volume"]["contribution"] == pytest.approx(8.18, abs=0.01)
    assert comps["budget"]["contribution"] == pytest.approx(11.25, abs=0.01)
    assert comps["competition"]["contribution"] == pytest.approx(14.92, abs=0.01)
    assert comps["freshness"]["contribution"] == pytest.approx(5.95, abs=0.01)
    assert comps["rating"]["contribution"] == pytest.approx(4.38, abs=0.01)
    # the six rounded contribution bars sum to the §4 total, 70.80
    assert round(sum(c["contribution"] for c in res.breakdown["components"]), 2) == pytest.approx(
        70.80, abs=0.02
    )
    inputs = res.breakdown["inputs"]
    assert inputs["hiring_rate_adjusted"] == pytest.approx(74.62, abs=0.01)
    assert inputs["velocity_source"] == "current_over_age"
    assert inputs["velocity_bph"] == pytest.approx(0.6667, abs=1e-3)
    assert inputs["snapshot_count"] == 1
    assert res.breakdown["normalized"] is False
