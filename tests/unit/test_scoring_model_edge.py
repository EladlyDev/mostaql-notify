"""Exhaustive edge-case / branch / property tests for the PURE scorer (scoring/model.py).

Complements ``test_scoring_model.py`` and ``test_scoring_edge.py`` by closing the remaining
branches: the all-zero / non-1 / negative / NaN / inf weight paths, every component's documented
floor (including ``client=None``), the degenerate-settings denominators, the velocity branches
(trajectory vs current-over-age, zero-duration window, negative delta, vel_cap=0), the age helpers
(both timestamps None, naive datetimes, future ``posted_at``), the breakdown shape + inputs echo,
determinism, the worked §4 example, the JSON-friendly ``_num`` helper, and the non-finite
``raw_score`` guard. Everything is pure: ``SimpleNamespace`` stubs + a fixed injected ``now_utc`` +
a hermetic ``FakeSettings`` (no DB), so each assertion is deterministic.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from mostaql_notifier.scoring import model

NOW = datetime(2026, 6, 28, 10, 0, 0, tzinfo=timezone.utc)

# The Feature-4 defaults (mirrors settings_store.DEFAULTS) plus the budget basis/rates the reused
# ``qualify.filters.budget_usd`` reads. A FakeSettings keeps these tests hermetic (no DB / fixture).
_DEFAULTS = {
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
    "budget_comparison_basis": "max",
    "currency_usd_rates": {"USD": 1.0, "EGP": 0.02},
}


class FakeSettings:
    """A lightweight, mutable ``SettingsStore`` stand-in returning chosen values per key/type."""

    def __init__(self, **over):
        self._v = dict(_DEFAULTS)
        self._v.update(over)

    def get_float(self, key):
        return float(self._v[key])

    def get_int(self, key):
        return int(self._v[key])

    def get_bool(self, key):
        return bool(self._v[key])

    def get_str(self, key):
        return str(self._v[key])

    def get_json(self, key):
        return self._v[key]

    def get_decimal(self, key):
        return Decimal(str(self._v[key]))


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


def _score(project, client, settings, now_utc=NOW):
    return model.score_project(project, client, settings=settings, now_utc=now_utc)


def _comp(res, key):
    return {c["key"]: c for c in res.breakdown["components"]}[key]


def _sub(res, key):
    return _comp(res, key)["sub_score"]


# --------------------------------------------------------------------------- §2 weight normalization


def test_default_weights_sum_one_not_flagged():
    res = _score(_proj(), _cli(), FakeSettings())
    assert res.breakdown["normalized"] is False  # |W − 1| ≤ 1e-9
    assert res.breakdown["weights"]["sum"] == pytest.approx(1.0, abs=1e-9)


def test_all_zero_weights_equal_sixth_fallback_flagged():
    s = FakeSettings(**{k: 0.0 for k in model._WEIGHT_KEYS})
    res = _score(_proj(), _cli(), s)
    assert res.breakdown["normalized"] is True
    nw = res.breakdown["weights"]["normalized"]
    assert all(v == pytest.approx(1 / 6, abs=1e-6) for v in nw.values())
    assert 0.0 <= res.score <= 100.0


def test_arbitrary_positive_weights_flagged_and_per_component_ratio():
    # W = 2.0 (defaults × 2) ⇒ each normalized weight = w / total, summing to 1.
    weights = [0.70, 0.30, 0.30, 0.40, 0.20, 0.10]
    s = FakeSettings(**dict(zip(model._WEIGHT_KEYS, weights, strict=True)))
    res = _score(_proj(), _cli(), s)
    assert res.breakdown["normalized"] is True
    assert res.breakdown["weights"]["sum"] == pytest.approx(2.0, abs=1e-9)
    nw = res.breakdown["weights"]["normalized"]
    assert sum(nw.values()) == pytest.approx(1.0, abs=1e-9)
    assert nw["hiring_rate"] == pytest.approx(0.70 / 2.0, abs=1e-6)
    assert nw["competition"] == pytest.approx(0.40 / 2.0, abs=1e-6)


def test_doubling_weights_is_scale_invariant():
    base = _score(_proj(), _cli(), FakeSettings()).score
    weights = [w * 2 for w in (0.35, 0.15, 0.15, 0.20, 0.10, 0.05)]
    s = FakeSettings(**dict(zip(model._WEIGHT_KEYS, weights, strict=True)))
    assert _score(_proj(), _cli(), s).score == pytest.approx(base, abs=1e-6)


def test_negative_weight_sanitized_to_zero():
    s = FakeSettings(score_weight_rating=-5.0)  # negative ⇒ treated as 0.0
    res = _score(_proj(), _cli(), s)
    assert res.breakdown["weights"]["configured"]["rating"] == 0.0
    assert res.breakdown["weights"]["normalized"]["rating"] == 0.0
    assert _comp(res, "rating")["contribution"] == 0.0


def test_nan_and_inf_weights_sanitized_to_zero():
    s = FakeSettings(score_weight_hire_volume=float("nan"), score_weight_budget=float("inf"))
    res = _score(_proj(), _cli(), s)
    cfg = res.breakdown["weights"]["configured"]
    assert cfg["hire_volume"] == 0.0
    assert cfg["budget"] == 0.0
    assert math.isfinite(res.score) and 0.0 <= res.score <= 100.0


# --------------------------------------------------------------------------- client=None floors


def test_missing_client_hits_component_floors():
    res = _score(_proj(), None, FakeSettings())
    # hiring_rate: r=baseline, n=0 ⇒ r_adj=baseline ⇒ baseline/100 = 0.5
    assert _sub(res, "hiring_rate") == pytest.approx(0.5, abs=1e-9)
    assert _sub(res, "hire_volume") == pytest.approx(0.0, abs=1e-9)  # h=0
    assert _sub(res, "rating") == pytest.approx(0.5, abs=1e-9)       # neutral
    assert res.breakdown["inputs"]["hiring_rate"] is None
    assert res.breakdown["inputs"]["avg_rating"] is None


# --------------------------------------------------------------------------- (a) hiring-rate shrink


def test_hiring_rate_n_zero_denominator_is_k():
    # n=0 ⇒ r_adj = (r·0 + b·k)/(0+k) = b ⇒ sub = b/100 = 0.5 regardless of r.
    res = _score(_proj(), _cli(hiring_rate=90.0, projects_posted=0), FakeSettings())
    assert _sub(res, "hiring_rate") == pytest.approx(0.5, abs=1e-9)


def test_hiring_rate_none_uses_baseline():
    res = _score(_proj(), _cli(hiring_rate=None, projects_posted=10), FakeSettings())
    assert _sub(res, "hiring_rate") == pytest.approx(0.5, abs=1e-9)  # r=b ⇒ r_adj=b
    assert res.breakdown["inputs"]["hiring_rate"] is None


def test_hiring_rate_shrink_k_zero_uses_raw_rate():
    # k=0, n=8 ⇒ denom=n ⇒ r_adj = r ⇒ sub = r/100.
    s = FakeSettings(score_hiring_shrink_k=0)
    res = _score(_proj(), _cli(hiring_rate=90.0, projects_posted=8), s)
    assert _sub(res, "hiring_rate") == pytest.approx(0.90, abs=1e-9)


def test_hiring_rate_shrink_k_zero_and_n_zero_falls_back_to_baseline():
    # k=0 AND n=0 ⇒ denom=0 ⇒ guarded ⇒ baseline ⇒ 0.5 (never divides by zero).
    s = FakeSettings(score_hiring_shrink_k=0)
    res = _score(_proj(), _cli(hiring_rate=90.0, projects_posted=0), s)
    assert _sub(res, "hiring_rate") == pytest.approx(0.5, abs=1e-9)


# --------------------------------------------------------------------------- (b) hire volume


def test_hire_volume_halfsat_zero_with_no_hires_is_floor():
    # s=0 and h=0 ⇒ denom=0 ⇒ guarded ⇒ 0.0 floor.
    s = FakeSettings(score_hire_volume_halfsat=0)
    res = _score(_proj(), _cli(hires_count=0), s)
    assert _sub(res, "hire_volume") == pytest.approx(0.0, abs=1e-9)


def test_hire_volume_halfsat_zero_with_hires_saturates():
    # s=0 and h>0 ⇒ h/h = 1.0.
    s = FakeSettings(score_hire_volume_halfsat=0)
    res = _score(_proj(), _cli(hires_count=4), s)
    assert _sub(res, "hire_volume") == pytest.approx(1.0, abs=1e-9)


def test_hire_volume_large_h_approaches_one():
    res = _score(_proj(), _cli(hires_count=10_000), FakeSettings())
    assert _sub(res, "hire_volume") == pytest.approx(1.0, abs=2e-3)
    assert _sub(res, "hire_volume") < 1.0  # Hill curve never reaches exactly 1


# --------------------------------------------------------------------------- (c) budget


def test_budget_usd_none_floor_and_raw_none():
    res = _score(_proj(currency="JPY"), _cli(), FakeSettings())  # not in rates ⇒ None
    assert _sub(res, "budget") == pytest.approx(0.0, abs=1e-9)
    assert _comp(res, "budget")["raw"] is None
    assert res.breakdown["inputs"]["budget_usd"] is None


def test_budget_tier2_downscales():
    res = _score(_proj(budget_max=Decimal("750"), tier=2), _cli(), FakeSettings())
    assert _sub(res, "budget") == pytest.approx(0.75 * 0.6, abs=1e-9)
    assert res.breakdown["inputs"]["tier"] == 2


@pytest.mark.parametrize("tier", [None, 1])
def test_budget_tier_none_or_one_no_scale(tier):
    res = _score(_proj(budget_max=Decimal("750"), tier=tier), _cli(), FakeSettings())
    assert _sub(res, "budget") == pytest.approx(0.75, abs=1e-9)


def test_budget_cap_zero_is_floor():
    s = FakeSettings(score_budget_cap_usd=0)
    res = _score(_proj(budget_max=Decimal("750")), _cli(), s)
    assert _sub(res, "budget") == pytest.approx(0.0, abs=1e-9)


def test_budget_above_cap_clamps_to_one():
    res = _score(_proj(budget_max=Decimal("50000"), tier=1), _cli(), FakeSettings())
    assert _sub(res, "budget") == pytest.approx(1.0, abs=1e-9)


def test_budget_decimal_coerced_to_float_raw():
    res = _score(_proj(budget_max=Decimal("750")), _cli(), FakeSettings())
    raw = _comp(res, "budget")["raw"]
    assert raw == pytest.approx(750.0, abs=1e-9) and isinstance(raw, float)
    assert isinstance(res.breakdown["inputs"]["budget_usd"], float)


# --------------------------------------------------------------------------- (d) competition


def test_competition_bids_none_is_uncrowded():
    res = _score(_proj(bids_count=None, snapshots=[]), _cli(), FakeSettings())
    assert _sub(res, "competition") == pytest.approx(1.0, abs=1e-9)
    assert res.breakdown["inputs"]["bids_count"] == 0


def test_competition_trajectory_source_with_two_snapshots():
    snaps = [_snap(NOW - timedelta(hours=4), 4), _snap(NOW - timedelta(hours=2), 10)]
    res = _score(_proj(bids_count=10, snapshots=snaps), _cli(), FakeSettings())
    assert res.breakdown["inputs"]["velocity_source"] == "trajectory"
    assert res.breakdown["inputs"]["velocity_bph"] == pytest.approx(3.0, abs=1e-6)
    assert res.breakdown["inputs"]["snapshot_count"] == 2


def test_competition_current_over_age_with_fewer_than_two_snapshots():
    res = _score(_proj(bids_count=6, snapshots=[_snap(NOW, 6)]), _cli(), FakeSettings())
    assert res.breakdown["inputs"]["velocity_source"] == "current_over_age"
    assert res.breakdown["inputs"]["velocity_bph"] == pytest.approx(6 / 9, abs=1e-4)


def test_competition_zero_duration_window_no_zero_division():
    # Two snapshots captured at the SAME instant ⇒ Δhours guarded by _EPS, velocity finite.
    same = NOW - timedelta(hours=1)
    snaps = [_snap(same, 5), _snap(same, 9)]
    res = _score(_proj(bids_count=9, snapshots=snaps), _cli(), FakeSettings())
    vel = res.breakdown["inputs"]["velocity_bph"]
    assert vel is not None and math.isfinite(vel)
    # Δbids=4 over ε hours ⇒ enormous velocity ⇒ vel sub-score clamps to 0.
    assert math.isfinite(res.score)


def test_competition_vel_cap_zero_zeroes_velocity_term():
    # vel_cap=0 ⇒ velocity sub-score = 0 ⇒ sub_d = crowd / 2.
    s = FakeSettings(score_competition_vel_cap=0.0)
    res = _score(_proj(bids_count=6, snapshots=[]), _cli(), s)
    crowd = 1.0 - 6 / (6 + 15)
    assert _sub(res, "competition") == pytest.approx(crowd / 2.0, abs=1e-4)


def test_competition_negative_delta_bids_clamped_to_zero():
    # Bids dropped between snapshots (5 → 2): Δbids clamps to 0 ⇒ velocity 0 ⇒ vel term 1.0.
    snaps = [_snap(NOW - timedelta(hours=4), 5), _snap(NOW - timedelta(hours=2), 2)]
    res = _score(_proj(bids_count=2, snapshots=snaps), _cli(), FakeSettings())
    assert res.breakdown["inputs"]["velocity_bph"] == pytest.approx(0.0, abs=1e-9)
    crowd = 1.0 - 2 / (2 + 15)
    assert _sub(res, "competition") == pytest.approx((crowd + 1.0) / 2.0, abs=1e-4)


# --------------------------------------------------------------------------- (e) freshness component


def test_freshness_component_age_equals_halflife_is_half():
    res = _score(_proj(posted_at=NOW - timedelta(hours=12)), _cli(), FakeSettings())
    assert _sub(res, "freshness") == pytest.approx(0.5, abs=1e-9)


def test_freshness_component_halflife_zero_is_newest():
    s = FakeSettings(score_freshness_halflife_hours=0.0)
    res = _score(_proj(posted_at=NOW - timedelta(hours=100)), _cli(), s)
    assert _sub(res, "freshness") == pytest.approx(1.0, abs=1e-9)


def test_freshness_component_future_posted_at_clamped_to_newest():
    res = _score(_proj(posted_at=NOW + timedelta(hours=5)), _cli(), FakeSettings())
    assert _sub(res, "freshness") == pytest.approx(1.0, abs=1e-9)
    assert res.breakdown["inputs"]["age_hours"] == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------------------- (f) rating


def test_rating_none_is_neutral():
    res = _score(_proj(), _cli(avg_rating=None, reviews_count=10), FakeSettings())
    assert _sub(res, "rating") == pytest.approx(0.5, abs=1e-9)


def test_rating_min_reviews_zero_full_confidence():
    s = FakeSettings(score_rating_min_reviews=0)
    res = _score(_proj(), _cli(avg_rating=5.0, reviews_count=0), s)
    assert _sub(res, "rating") == pytest.approx(1.0, abs=1e-9)  # confidence forced to 1.0


def test_rating_high_and_low_clamp():
    hi = _sub(_score(_proj(), _cli(avg_rating=5.0, reviews_count=10), FakeSettings()), "rating")
    lo = _sub(_score(_proj(), _cli(avg_rating=1.0, reviews_count=10), FakeSettings()), "rating")
    assert hi == pytest.approx(1.0, abs=1e-9)
    assert lo == pytest.approx(0.0, abs=1e-9)


def test_nan_rating_falls_to_neutral_floor():
    # A NaN avg_rating drives the rating sub-score non-finite ⇒ _finalize coerces it to the 0.5 floor.
    res = _score(_proj(), _cli(avg_rating=float("nan"), reviews_count=10), FakeSettings())
    assert _sub(res, "rating") == pytest.approx(0.5, abs=1e-9)
    assert math.isfinite(res.score)


def test_rating_out_of_range_stays_clamped():
    # A nonsensical rating beyond 5 still clamps into [0, 1].
    res = _score(_proj(), _cli(avg_rating=50.0, reviews_count=10), FakeSettings())
    assert 0.0 <= _sub(res, "rating") <= 1.0
    assert _sub(res, "rating") == pytest.approx(1.0, abs=1e-9)


# --------------------------------------------------------------------------- age helpers


def test_age_falls_back_to_scraped_at():
    res = _score(_proj(posted_at=None, scraped_at=NOW - timedelta(hours=9)), _cli(), FakeSettings())
    assert res.breakdown["inputs"]["age_hours"] == pytest.approx(9.0, abs=1e-6)


def test_age_both_timestamps_none_is_zero():
    # Structurally impossible (scraped_at is NOT NULL) but must degrade to age 0, never raise.
    res = _score(_proj(posted_at=None, scraped_at=None), _cli(), FakeSettings())
    assert res.breakdown["inputs"]["age_hours"] == pytest.approx(0.0, abs=1e-9)
    assert _sub(res, "freshness") == pytest.approx(1.0, abs=1e-9)


def test_naive_posted_at_assumed_utc():
    naive = (NOW - timedelta(hours=9)).replace(tzinfo=None)
    res = _score(_proj(posted_at=naive, scraped_at=naive), _cli(), FakeSettings())
    assert res.breakdown["inputs"]["age_hours"] == pytest.approx(9.0, abs=1e-6)


def test_naive_now_utc_assumed_utc():
    naive_now = NOW.replace(tzinfo=None)
    res = _score(_proj(), _cli(), FakeSettings(), now_utc=naive_now)
    assert math.isfinite(res.score)
    assert res.breakdown["computed_at"] == "2026-06-28T10:00:00Z"


# --------------------------------------------------------------------------- breakdown shape


def test_breakdown_shape_and_inputs_keys():
    res = _score(_proj(snapshots=[_snap(NOW - timedelta(hours=9), 6)]), _cli(), FakeSettings())
    bd = res.breakdown

    assert set(bd) == {"score", "normalized", "computed_at", "components", "weights", "inputs"}
    assert len(bd["components"]) == 6
    assert [c["key"] for c in bd["components"]] == [
        "hiring_rate", "hire_volume", "budget", "competition", "freshness", "rating",
    ]
    assert [c["label"] for c in bd["components"]] == [
        "معدل التوظيف", "حجم التوظيف", "الميزانية", "المنافسة", "الحداثة", "تقييم العميل",
    ]
    for comp in bd["components"]:
        assert set(comp) == {"key", "label", "raw", "sub_score", "weight", "contribution"}
        assert 0.0 <= comp["sub_score"] <= 1.0

    assert set(bd["weights"]) == {"configured", "sum", "normalized"}
    assert set(bd["inputs"]) == {
        "hiring_rate", "projects_posted", "hiring_rate_adjusted", "hires_count", "budget_usd",
        "tier", "bids_count", "posted_at", "age_hours", "avg_rating", "reviews_count",
        "snapshot_count", "velocity_bph", "velocity_source",
    }
    json.dumps(bd)  # persisted verbatim ⇒ must be JSON-serializable


def test_contributions_sum_to_score():
    res = _score(_proj(snapshots=[_snap(NOW - timedelta(hours=9), 6)]), _cli(), FakeSettings())
    total = sum(c["contribution"] for c in res.breakdown["components"])
    assert total == pytest.approx(res.breakdown["score"], abs=0.05)
    assert 0.0 <= res.score <= 100.0


def test_worked_example_reproduces_70_80():
    res = _score(_proj(snapshots=[_snap(NOW - timedelta(hours=9), 6)]), _cli(), FakeSettings())
    assert res.score == pytest.approx(70.80, abs=0.05)
    comps = {c["key"]: c for c in res.breakdown["components"]}
    assert comps["hiring_rate"]["contribution"] == pytest.approx(26.12, abs=0.01)
    assert comps["hire_volume"]["contribution"] == pytest.approx(8.18, abs=0.01)
    assert comps["budget"]["contribution"] == pytest.approx(11.25, abs=0.01)
    assert comps["competition"]["contribution"] == pytest.approx(14.92, abs=0.01)
    assert comps["freshness"]["contribution"] == pytest.approx(5.95, abs=0.01)
    assert comps["rating"]["contribution"] == pytest.approx(4.38, abs=0.01)
    inputs = res.breakdown["inputs"]
    assert inputs["hiring_rate_adjusted"] == pytest.approx(74.62, abs=0.01)
    assert inputs["velocity_source"] == "current_over_age"
    assert res.breakdown["normalized"] is False


def test_determinism_identical_inputs_identical_breakdown():
    p = _proj(snapshots=[_snap(NOW - timedelta(hours=9), 6)])
    a = _score(p, _cli(), FakeSettings())
    b = _score(p, _cli(), FakeSettings())
    assert a.score == b.score
    assert a.breakdown == b.breakdown


# --------------------------------------------------------------------------- helper / guard branches


def test_num_helper_coerces_decimal_and_passes_through():
    assert model._num(None) is None
    out = model._num(Decimal("750.5"))
    assert out == pytest.approx(750.5) and isinstance(out, float)
    assert model._num(5) == 5
    assert model._num(2.5) == 2.5


def test_ensure_utc_naive_assumed_utc():
    naive = datetime(2026, 6, 28, 10, 0, 0)
    out = model._ensure_utc(naive)
    assert out.tzinfo is timezone.utc
    assert out == NOW


def test_non_finite_raw_score_clamps_to_zero(monkeypatch):
    # Force a component to emit a non-finite sub-score (bypassing _finalize) ⇒ raw_score is inf ⇒
    # the §85-88 guard clamps it to 0.0 rather than persisting a NaN/inf score.
    monkeypatch.setattr(
        model, "_hiring_rate",
        lambda client, settings: (float("inf"), 90.0, {"projects_posted": 8, "hiring_rate_adjusted": None}),
    )
    res = _score(_proj(), _cli(), FakeSettings())
    assert res.score == 0.0
    assert res.breakdown["score"] == 0.0
