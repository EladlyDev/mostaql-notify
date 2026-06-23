"""Exhaustive unit tests for qualify/filters.py.

Targets every branch of ``budget_usd`` (basis min/max/midpoint with both/one/neither bound),
non-trivial currency conversion, the gate ordering of ``qualify`` (fail-closed short-circuits),
tier boundary arithmetic, and the ``min_hiring_rate`` strictly-greater boundary.

Constitution bars exercised here:
  * Fail-closed: missing/unparseable signal DISQUALIFIES (never admit on a guess).
  * 0% hiring rate is a REAL value but strictly-greater means it FAILS at threshold 0.
  * Unknown currency (None / not-in-rates) => budget None.
  * Config over code: every threshold read from the settings table.

Currently-uncovered lines targeted: 40 (basis "min"), 42-45 (basis "midpoint"),
83 (exclusion_passes True pass-through reached).
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from mostaql_notifier.db.models import (
    Client,
    EvalStatus,
    Project,
    ProjectStatus,
    Setting,
)
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.qualify.budget_policy import BudgetPolicy
from mostaql_notifier.qualify.filters import (
    Qualification,
    budget_usd,
    exclusion_passes,
    qualify,
)

# --------------------------------------------------------------------------- helpers


def _client(hiring_rate):
    return Client(
        mostaql_id="derived:abc",
        name="عميل",
        hiring_rate=hiring_rate,
        last_refreshed_at=utcnow(),
        first_seen_at=utcnow(),
        raw={},
    )


def _project(
    settings,
    *,
    budget_min=None,
    budget_max=Decimal(300),
    currency="USD",
    status=ProjectStatus.open,
    category=None,
):
    return Project(
        mostaql_id="p1",
        title="مشروع تطوير",
        budget_min=budget_min,
        budget_max=budget_max,
        currency=currency,
        scraped_at=utcnow(),
        site_status=status,
        eval_status=EvalStatus.pending,
        category=settings.get_str("category_slug") if category is None else category,
        raw={},
    )


def _policy(active_floor=Decimal(250)):
    return BudgetPolicy(active_floor=Decimal(active_floor))


def _set_basis(session, settings, basis: str) -> None:
    row = session.get(Setting, "budget_comparison_basis")
    row.value = basis
    session.commit()
    settings.reload()


def _set_rates(session, settings, rates: dict) -> None:
    """Write a JSON-typed setting (set_setting's str() would emit invalid JSON for a dict)."""
    row = session.get(Setting, "currency_usd_rates")
    row.value = json.dumps(rates)
    row.value_type = "json"
    session.commit()
    settings.reload()


def _set_int(session, settings, key: str, value) -> None:
    row = session.get(Setting, key)
    row.value = str(value)
    session.commit()
    settings.reload()


# =========================================================================== budget_usd
# ----- basis "max" (default) ------------------------------------------------


def test_basis_max_uses_max_when_both_present(db_session, settings):
    proj = _project(settings, budget_min=Decimal(100), budget_max=Decimal(300))
    assert settings.get_str("budget_comparison_basis") == "max"
    assert budget_usd(proj, settings) == Decimal(300)


def test_basis_max_falls_back_to_min_when_only_min(db_session, settings):
    proj = _project(settings, budget_min=Decimal(120), budget_max=None)
    assert budget_usd(proj, settings) == Decimal(120)


def test_basis_max_uses_max_when_only_max(db_session, settings):
    proj = _project(settings, budget_min=None, budget_max=Decimal(300))
    assert budget_usd(proj, settings) == Decimal(300)


def test_basis_max_neither_bound_is_none(db_session, settings):
    proj = _project(settings, budget_min=None, budget_max=None)
    assert budget_usd(proj, settings) is None


# ----- basis "min" (line 40) ------------------------------------------------


def test_basis_min_uses_min_when_both_present(db_session, settings):
    _set_basis(db_session, settings, "min")
    proj = _project(settings, budget_min=Decimal(100), budget_max=Decimal(300))
    assert budget_usd(proj, settings) == Decimal(100)


def test_basis_min_uses_min_when_only_min(db_session, settings):
    _set_basis(db_session, settings, "min")
    proj = _project(settings, budget_min=Decimal(140), budget_max=None)
    assert budget_usd(proj, settings) == Decimal(140)


def test_basis_min_falls_back_to_max_when_only_max(db_session, settings):
    # line 40: `bmin if bmin is not None else bmax` -> with min absent, uses max.
    _set_basis(db_session, settings, "min")
    proj = _project(settings, budget_min=None, budget_max=Decimal(300))
    assert budget_usd(proj, settings) == Decimal(300)


def test_basis_min_neither_bound_is_none(db_session, settings):
    _set_basis(db_session, settings, "min")
    proj = _project(settings, budget_min=None, budget_max=None)
    assert budget_usd(proj, settings) is None


# ----- basis "midpoint" (lines 42-45) ---------------------------------------


def test_basis_midpoint_averages_both_bounds(db_session, settings):
    _set_basis(db_session, settings, "midpoint")
    proj = _project(settings, budget_min=Decimal(100), budget_max=Decimal(300))
    assert budget_usd(proj, settings) == Decimal(200)


def test_basis_midpoint_odd_sum_is_exact_decimal(db_session, settings):
    # (100 + 305)/2 = 202.5 — Decimal division must stay exact, no float drift.
    _set_basis(db_session, settings, "midpoint")
    proj = _project(settings, budget_min=Decimal(100), budget_max=Decimal(305))
    result = budget_usd(proj, settings)
    assert result == Decimal("202.5")
    assert isinstance(result, Decimal)


def test_basis_midpoint_only_max_uses_max(db_session, settings):
    # line 45: bmin None -> `value = bmax if bmax is not None else bmin` -> bmax.
    _set_basis(db_session, settings, "midpoint")
    proj = _project(settings, budget_min=None, budget_max=Decimal(300))
    assert budget_usd(proj, settings) == Decimal(300)


def test_basis_midpoint_only_min_uses_min(db_session, settings):
    # line 45: bmax None -> falls back to bmin.
    _set_basis(db_session, settings, "midpoint")
    proj = _project(settings, budget_min=Decimal(160), budget_max=None)
    assert budget_usd(proj, settings) == Decimal(160)


def test_basis_midpoint_neither_bound_is_none(db_session, settings):
    _set_basis(db_session, settings, "midpoint")
    proj = _project(settings, budget_min=None, budget_max=None)
    assert budget_usd(proj, settings) is None


# ----- unknown / unrecognised basis falls into the "max" else branch --------


def test_unknown_basis_behaves_like_max(db_session, settings):
    _set_basis(db_session, settings, "totally_unknown_basis")
    proj = _project(settings, budget_min=Decimal(100), budget_max=Decimal(300))
    assert budget_usd(proj, settings) == Decimal(300)


# =========================================================================== currency


def test_currency_none_is_none(db_session, settings):
    proj = _project(settings, currency=None)
    assert budget_usd(proj, settings) is None


def test_currency_not_in_rates_is_none(db_session, settings):
    # Default rates contain only USD; EUR is absent -> fail-closed None.
    proj = _project(settings, currency="EUR")
    assert budget_usd(proj, settings) is None


def test_currency_usd_default_rate_is_identity(db_session, settings):
    proj = _project(settings, budget_max=Decimal(300), currency="USD")
    assert budget_usd(proj, settings) == Decimal(300)


def test_nontrivial_rate_sar_scales(db_session, settings):
    # Non-trivial rate table: SAR present -> scales; "EUR" still absent -> None.
    _set_rates(db_session, settings, {"USD": 1.0, "SAR": 0.27})
    proj = _project(settings, budget_max=Decimal(1000), currency="SAR")
    assert budget_usd(proj, settings) == Decimal("270.0")


def test_nontrivial_rate_eur_still_unknown(db_session, settings):
    _set_rates(db_session, settings, {"USD": 1.0, "SAR": 0.27})
    proj = _project(settings, budget_max=Decimal(1000), currency="EUR")
    assert budget_usd(proj, settings) is None


def test_nontrivial_rate_usd_unaffected(db_session, settings):
    _set_rates(db_session, settings, {"USD": 1.0, "SAR": 0.27})
    proj = _project(settings, budget_max=Decimal(300), currency="USD")
    assert budget_usd(proj, settings) == Decimal(300)


def test_rate_applied_after_basis_selection_min(db_session, settings):
    # Basis min picks 1000, rate 0.27 -> 270; ensures conversion happens post-basis.
    _set_basis(db_session, settings, "min")
    _set_rates(db_session, settings, {"USD": 1.0, "SAR": 0.27})
    proj = _project(settings, budget_min=Decimal(1000), budget_max=Decimal(2000), currency="SAR")
    assert budget_usd(proj, settings) == Decimal("270.00")


def test_empty_rate_table_disqualifies_even_usd(db_session, settings):
    # Fail-closed: if the operator empties the rate table, USD itself becomes unknown.
    _set_rates(db_session, settings, {})
    proj = _project(settings, budget_max=Decimal(300), currency="USD")
    assert budget_usd(proj, settings) is None


# =========================================================================== qualify gates
# ----- gate (1) hiring rate short-circuits before budget ---------------------


def test_hiring_none_short_circuits_before_budget(db_session, settings):
    # Even with an *unknown* budget currency, hiring None must win the reason.
    proj = _project(settings, currency="EUR")  # budget would be None
    result = qualify(proj, _client(None), _policy(), settings)
    assert result.qualified is False
    assert result.tier is None
    assert result.reason == "client_hiring_rate_unknown"


def test_client_none_short_circuits(db_session, settings):
    proj = _project(settings, currency="EUR")
    result = qualify(proj, None, _policy(), settings)
    assert result.qualified is False
    assert result.reason == "client_hiring_rate_unknown"


def test_hiring_below_min_short_circuits_before_budget(db_session, settings):
    # min_hiring_rate default is 0; hiring 0.0 must FAIL (strictly greater).
    proj = _project(settings, currency="EUR")  # budget unknown, but hiring gate fires first
    result = qualify(proj, _client(0.0), _policy(), settings)
    assert result.qualified is False
    assert result.reason == "client_hiring_rate_below_min"


# ----- min_hiring_rate strictly-greater boundary -----------------------------


def test_hiring_equal_threshold_disqualifies(db_session, settings):
    _set_int(db_session, settings, "min_hiring_rate", 50)
    proj = _project(settings)
    result = qualify(proj, _client(50.0), _policy(), settings)
    assert result.qualified is False
    assert result.reason == "client_hiring_rate_below_min"


def test_hiring_just_above_threshold_qualifies(db_session, settings):
    _set_int(db_session, settings, "min_hiring_rate", 50)
    proj = _project(settings, budget_max=Decimal(300), currency="USD")
    result = qualify(proj, _client(50.01), _policy(), settings)
    assert result.qualified is True


def test_hiring_just_below_threshold_disqualifies(db_session, settings):
    _set_int(db_session, settings, "min_hiring_rate", 50)
    proj = _project(settings)
    result = qualify(proj, _client(49.99), _policy(), settings)
    assert result.qualified is False
    assert result.reason == "client_hiring_rate_below_min"


def test_hiring_default_zero_threshold_tiny_positive_qualifies(db_session, settings):
    # 0.0001 > 0 -> passes the hiring gate (0% is a distinct, failing value; >0% passes).
    proj = _project(settings, budget_max=Decimal(300), currency="USD")
    result = qualify(proj, _client(0.0001), _policy(), settings)
    assert result.qualified is True


# ----- gate (2) budget unknown / floor boundary ------------------------------


def test_budget_unknown_after_hiring_pass(db_session, settings):
    proj = _project(settings, currency="EUR")  # unknown currency -> budget None
    result = qualify(proj, _client(0.75), _policy(), settings)
    assert result.qualified is False
    assert result.reason == "budget_unknown"


def test_budget_exactly_equals_active_floor_qualifies(db_session, settings):
    # usd == active_floor must qualify (gate uses `usd < floor`).
    proj = _project(settings, budget_max=Decimal(250), currency="USD")
    result = qualify(proj, _client(0.75), _policy(active_floor=Decimal(250)), settings)
    assert result.qualified is True


def test_budget_just_below_active_floor_disqualifies(db_session, settings):
    proj = _project(settings, budget_max=Decimal("249.99"), currency="USD")
    result = qualify(proj, _client(0.75), _policy(active_floor=Decimal(250)), settings)
    assert result.qualified is False
    assert result.reason == "budget_below_floor"


def test_budget_just_above_active_floor_qualifies(db_session, settings):
    proj = _project(settings, budget_max=Decimal("250.01"), currency="USD")
    result = qualify(proj, _client(0.75), _policy(active_floor=Decimal(250)), settings)
    assert result.qualified is True


# ----- gate ordering: budget evaluated BEFORE open/category -----------------


def test_budget_below_floor_beats_closed_status(db_session, settings):
    # A closed project that is also below floor reports the budget reason (budget gate first).
    proj = _project(settings, budget_max=Decimal(10), currency="USD", status=ProjectStatus.closed)
    result = qualify(proj, _client(0.75), _policy(active_floor=Decimal(250)), settings)
    assert result.qualified is False
    assert result.reason == "budget_below_floor"


def test_budget_below_floor_beats_wrong_category(db_session, settings):
    proj = _project(settings, budget_max=Decimal(10), currency="USD", category="design")
    result = qualify(proj, _client(0.75), _policy(active_floor=Decimal(250)), settings)
    assert result.qualified is False
    assert result.reason == "budget_below_floor"


# ----- gate (3) open / category evaluated after budget ----------------------


def test_closed_project_after_budget_pass(db_session, settings):
    proj = _project(settings, budget_max=Decimal(300), currency="USD", status=ProjectStatus.closed)
    result = qualify(proj, _client(0.75), _policy(), settings)
    assert result.qualified is False
    assert result.reason == "project_not_open"


def test_unknown_status_disqualifies(db_session, settings):
    # ProjectStatus.unknown is the fail-closed default; must not be treated as open.
    proj = _project(settings, budget_max=Decimal(300), currency="USD", status=ProjectStatus.unknown)
    result = qualify(proj, _client(0.75), _policy(), settings)
    assert result.qualified is False
    assert result.reason == "project_not_open"


def test_wrong_category_after_open_check(db_session, settings):
    proj = _project(settings, budget_max=Decimal(300), currency="USD", category="design")
    result = qualify(proj, _client(0.75), _policy(), settings)
    assert result.qualified is False
    assert result.reason == "wrong_category"


def test_open_and_wrong_category_orders_status_first(db_session, settings):
    # Closed + wrong category -> status reason fires before category.
    proj = _project(
        settings,
        budget_max=Decimal(300),
        currency="USD",
        status=ProjectStatus.closed,
        category="design",
    )
    result = qualify(proj, _client(0.75), _policy(), settings)
    assert result.reason == "project_not_open"


# ----- gate (4) exclusion pass-through (line 83 path reached) ----------------


def test_exclusion_passes_pure_passthrough_true(db_session, settings):
    # exclusion_passes always returns True in this feature.
    proj = _project(settings)
    assert exclusion_passes(proj, settings) is True
    proj2 = _project(settings, currency=None, status=ProjectStatus.closed, category="design")
    assert exclusion_passes(proj2, settings) is True


def test_fully_qualified_passes_through_exclusion_stage(db_session, settings):
    # A project clearing gates 1-3 reaches the exclusion stage and proceeds to tiering.
    # This exercises the not-excluded continuation past line 82/83.
    proj = _project(settings, budget_max=Decimal(300), currency="USD")
    result = qualify(proj, _client(0.75), _policy(), settings)
    assert result.qualified is True
    assert result.reason == "qualified"
    assert result.tier == 1


# =========================================================================== tiering


def test_tier1_when_usd_equals_primary_floor(db_session, settings):
    # usd == budget_primary_floor (250) -> tier 1 (gate uses `usd >= primary`).
    proj = _project(settings, budget_max=Decimal(250), currency="USD")
    result = qualify(proj, _client(0.75), _policy(active_floor=Decimal(100)), settings)
    assert result.qualified is True
    assert result.tier == 1


def test_tier1_when_usd_above_primary_floor(db_session, settings):
    proj = _project(settings, budget_max=Decimal("250.01"), currency="USD")
    result = qualify(proj, _client(0.75), _policy(active_floor=Decimal(100)), settings)
    assert result.qualified is True
    assert result.tier == 1


def test_tier2_below_primary_but_at_or_above_fallback_floor(db_session, settings):
    # Active floor lowered to fallback (100); usd 150 is < primary 250 -> tier 2.
    proj = _project(settings, budget_max=Decimal(150), currency="USD")
    result = qualify(proj, _client(0.75), _policy(active_floor=Decimal(100)), settings)
    assert result.qualified is True
    assert result.tier == 2


def test_tier2_just_below_primary_floor(db_session, settings):
    proj = _project(settings, budget_max=Decimal("249.99"), currency="USD")
    result = qualify(proj, _client(0.75), _policy(active_floor=Decimal(100)), settings)
    assert result.qualified is True
    assert result.tier == 2


def test_tier2_at_active_fallback_floor_boundary(db_session, settings):
    # usd == active_floor (100, the fallback) qualifies, and is below primary -> tier 2.
    proj = _project(settings, budget_max=Decimal(100), currency="USD")
    result = qualify(proj, _client(0.75), _policy(active_floor=Decimal(100)), settings)
    assert result.qualified is True
    assert result.tier == 2


def test_tier_reads_primary_floor_from_settings(db_session, settings):
    # Config over code: raising budget_primary_floor reclassifies a 300 project to tier 2.
    _set_int(db_session, settings, "budget_primary_floor", 500)
    proj = _project(settings, budget_max=Decimal(300), currency="USD")
    result = qualify(proj, _client(0.75), _policy(active_floor=Decimal(100)), settings)
    assert result.qualified is True
    assert result.tier == 2


# =========================================================================== full happy path w/ conversion


def test_qualify_with_nontrivial_currency_conversion(db_session, settings):
    # SAR 1000 * 0.27 = 270 USD >= primary 250 -> tier 1 qualified.
    _set_rates(db_session, settings, {"USD": 1.0, "SAR": 0.27})
    proj = _project(settings, budget_max=Decimal(1000), currency="SAR")
    result = qualify(proj, _client(0.75), _policy(active_floor=Decimal(100)), settings)
    assert result.qualified is True
    assert result.tier == 1


def test_qualify_conversion_drops_below_floor(db_session, settings):
    # SAR 800 * 0.27 = 216 USD < active_floor 250 -> disqualified for budget.
    _set_rates(db_session, settings, {"USD": 1.0, "SAR": 0.27})
    proj = _project(settings, budget_max=Decimal(800), currency="SAR")
    result = qualify(proj, _client(0.75), _policy(active_floor=Decimal(250)), settings)
    assert result.qualified is False
    assert result.reason == "budget_below_floor"


def test_qualification_dataclass_is_frozen(db_session, settings):
    q = Qualification(True, 1, "qualified")
    with pytest.raises(AttributeError):  # frozen dataclass -> FrozenInstanceError(AttributeError)
        q.qualified = False


# =========================================================================== basis fallback (design)
# Verified design decision (not a fail-closed violation): the comparison basis is a *preference*,
# not a hard requirement. With basis='min' and only the max bound present, budget_usd falls back to
# the present bound — symmetric with the well-tested basis='max' one-sided case — using a REAL
# observed number (it does not invent one), and qualification still requires a known currency and a
# floor. So this is intended, not a guess.


def test_basis_min_with_only_max_falls_back_to_present_bound(db_session, settings):
    _set_basis(db_session, settings, "min")
    proj = _project(settings, budget_min=None, budget_max=Decimal(300))
    assert budget_usd(proj, settings) == Decimal(300)
