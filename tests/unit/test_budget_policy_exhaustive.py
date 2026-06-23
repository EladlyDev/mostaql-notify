"""Exhaustive unit tests for the dynamic budget floor (``qualify/budget_policy``).

Focus areas (per assignment):
  * hysteresis boundaries around target / target+buffer (the strict ``<`` and ``>`` operators);
  * window-inclusion boundary (``qualified_at >= since`` — exactly-at-boundary is INCLUDED);
  * tier filtering (only ``tier == 1`` rows count; tier 2 / tier None are ignored);
  * Decimal-equality robustness across persistence and across scales (``250`` vs ``250.00``);
  * pass-through for a current floor that is neither primary nor fallback;
  * ``load_policy`` default (unset == primary) and ``save_policy``/``load_policy`` round-trip.

Time is frozen by monkeypatching ``budget_policy.utcnow`` so the ``since`` window edge is exact and
deterministic (no microsecond drift between the inserted row timestamp and the computed window).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from mostaql_notifier.config.settings_store import app_state_get, app_state_set
from mostaql_notifier.db.models import EvalStatus, Project, ProjectStatus
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.qualify import budget_policy as bp
from mostaql_notifier.qualify.budget_policy import (
    BudgetPolicy,
    load_policy,
    recompute_floor,
    save_policy,
)

# A fixed, timezone-aware UTC "now" so every window computation is reproducible.
FROZEN = datetime(2026, 6, 23, 12, 0, 0, tzinfo=timezone.utc)

PRIMARY = Decimal(250)
FALLBACK = Decimal(100)


@pytest.fixture
def frozen_now(monkeypatch):
    """Freeze ``budget_policy.utcnow`` so the ``since`` boundary is exact and stable."""
    monkeypatch.setattr(bp, "utcnow", lambda: FROZEN)
    return FROZEN


def _add_project(
    db_session,
    mostaql_id: str,
    *,
    tier,
    qualified_at,
    eval_status=EvalStatus.qualified,
):
    db_session.add(
        Project(
            mostaql_id=mostaql_id,
            scraped_at=FROZEN,
            site_status=ProjectStatus.open,
            eval_status=eval_status,
            tier=tier,
            qualified_at=qualified_at,
            raw={},
        )
    )


def _insert_tier1(db_session, n, *, qualified_at, prefix="t1"):
    for i in range(n):
        _add_project(db_session, f"{prefix}-{i}", tier=1, qualified_at=qualified_at)
    db_session.commit()


# --------------------------------------------------------------------------------------
# recompute_floor — hysteresis boundaries (the strict < / > operators)
# --------------------------------------------------------------------------------------


def test_primary_count_equals_target_stays_primary(db_session, settings, frozen_now):
    """At primary, count == target (10): ``10 < 10`` is False -> NOT lowered."""
    recent = frozen_now - timedelta(hours=1)
    _insert_tier1(db_session, 10, qualified_at=recent)
    assert recompute_floor(PRIMARY, settings, db_session) == PRIMARY


def test_primary_count_target_minus_one_drops_to_fallback(db_session, settings, frozen_now):
    """At primary, count == target-1 (9): ``9 < 10`` True -> drop to fallback."""
    recent = frozen_now - timedelta(hours=1)
    _insert_tier1(db_session, 9, qualified_at=recent)
    assert recompute_floor(PRIMARY, settings, db_session) == FALLBACK


def test_primary_zero_supply_drops_to_fallback(db_session, settings, frozen_now):
    """At primary with no recent supply at all: scarce -> fallback."""
    assert recompute_floor(PRIMARY, settings, db_session) == FALLBACK


def test_fallback_count_equals_target_plus_buffer_stays_fallback(db_session, settings, frozen_now):
    """At fallback, count == target+buffer (12): ``12 > 12`` False -> NOT raised (dead-band)."""
    recent = frozen_now - timedelta(hours=1)
    _insert_tier1(db_session, 12, qualified_at=recent)
    assert recompute_floor(FALLBACK, settings, db_session) == FALLBACK


def test_fallback_count_target_plus_buffer_plus_one_rises_to_primary(db_session, settings, frozen_now):
    """At fallback, count == target+buffer+1 (13): ``13 > 12`` True -> rise to primary."""
    recent = frozen_now - timedelta(hours=1)
    _insert_tier1(db_session, 13, qualified_at=recent)
    assert recompute_floor(FALLBACK, settings, db_session) == PRIMARY


def test_fallback_scarce_supply_holds_fallback(db_session, settings, frozen_now):
    """At fallback with scarce supply (count < target): no upward transition; stays fallback."""
    recent = frozen_now - timedelta(hours=1)
    _insert_tier1(db_session, 3, qualified_at=recent)
    assert recompute_floor(FALLBACK, settings, db_session) == FALLBACK


def test_primary_plentiful_supply_holds_primary(db_session, settings, frozen_now):
    """At primary with plentiful supply: no downward transition; stays primary (already high)."""
    recent = frozen_now - timedelta(hours=1)
    _insert_tier1(db_session, 20, qualified_at=recent)
    assert recompute_floor(PRIMARY, settings, db_session) == PRIMARY


# --------------------------------------------------------------------------------------
# recompute_floor — window-inclusion boundary (qualified_at >= since)
# --------------------------------------------------------------------------------------


def test_qualified_at_exactly_at_window_edge_is_included(db_session, settings, frozen_now):
    """A tier-1 row whose ``qualified_at`` == ``now - window_hours`` is INCLUDED (>= since).

    Insert exactly ``target`` (10) rows at the edge: if included, count == 10, so ``10 < 10`` is
    False and the primary floor is held. (If the edge were wrongly excluded, count would be 0 and
    the floor would drop to fallback.)
    """
    window_hours = settings.get_int("fallback_window_hours")
    edge = frozen_now - timedelta(hours=window_hours)
    _insert_tier1(db_session, 10, qualified_at=edge, prefix="edge")
    assert recompute_floor(PRIMARY, settings, db_session) == PRIMARY


def test_qualified_at_just_older_than_window_edge_is_excluded(db_session, settings, frozen_now):
    """A tier-1 row one microsecond older than the edge is EXCLUDED.

    Insert exactly ``target`` (10) rows just past the edge: excluded -> count 0 -> scarce -> drops
    to fallback. SQLite preserves microsecond resolution, so the boundary is crisp.
    """
    window_hours = settings.get_int("fallback_window_hours")
    just_older = frozen_now - timedelta(hours=window_hours) - timedelta(microseconds=1)
    _insert_tier1(db_session, 10, qualified_at=just_older, prefix="old")
    assert recompute_floor(PRIMARY, settings, db_session) == FALLBACK


def test_window_edge_inclusion_distinguishable_from_just_inside(db_session, settings, frozen_now):
    """A row just INSIDE the window (newer than edge) is obviously included too — sanity sibling."""
    window_hours = settings.get_int("fallback_window_hours")
    just_inside = frozen_now - timedelta(hours=window_hours) + timedelta(microseconds=1)
    _insert_tier1(db_session, 10, qualified_at=just_inside, prefix="inside")
    assert recompute_floor(PRIMARY, settings, db_session) == PRIMARY


# --------------------------------------------------------------------------------------
# recompute_floor — tier filtering (only tier == 1 counts)
# --------------------------------------------------------------------------------------


def test_only_tier1_counts_tier2_and_none_ignored(db_session, settings, frozen_now):
    """Tier-2 and tier-None qualified rows must NOT contribute to the supply count.

    Place exactly target-1 (9) genuine tier-1 rows (scarce -> would drop) plus a flood of tier-2
    and tier-None qualified rows inside the window. If those non-tier-1 rows were counted, the total
    would exceed target and the floor would be held; the correct behaviour is to drop to fallback.
    """
    recent = frozen_now - timedelta(hours=1)
    _insert_tier1(db_session, 9, qualified_at=recent, prefix="real")
    for i in range(50):
        _add_project(db_session, f"tier2-{i}", tier=2, qualified_at=recent)
    for i in range(50):
        _add_project(db_session, f"tierN-{i}", tier=None, qualified_at=recent)
    db_session.commit()
    assert recompute_floor(PRIMARY, settings, db_session) == FALLBACK


def test_tier2_and_none_do_not_block_rise(db_session, settings, frozen_now):
    """At fallback, 13 tier-1 rows rise to primary even if tier-2/None rows coexist (they're noise)."""
    recent = frozen_now - timedelta(hours=1)
    _insert_tier1(db_session, 13, qualified_at=recent, prefix="real")
    for i in range(7):
        _add_project(db_session, f"noise2-{i}", tier=2, qualified_at=recent)
        _add_project(db_session, f"noiseN-{i}", tier=None, qualified_at=recent)
    db_session.commit()
    assert recompute_floor(FALLBACK, settings, db_session) == PRIMARY


def test_tier2_only_supply_treated_as_scarce(db_session, settings, frozen_now):
    """Only tier-2 rows present (no tier-1): supply is effectively zero -> primary drops to fallback."""
    recent = frozen_now - timedelta(hours=1)
    for i in range(30):
        _add_project(db_session, f"only2-{i}", tier=2, qualified_at=recent)
    db_session.commit()
    assert recompute_floor(PRIMARY, settings, db_session) == FALLBACK


# --------------------------------------------------------------------------------------
# recompute_floor — Decimal-equality robustness
# --------------------------------------------------------------------------------------


def test_current_floor_scaled_decimal_still_matches_primary(db_session, settings, frozen_now):
    """A current floor expressed as ``Decimal('250.00')`` must compare equal to the primary 250.

    Scarce supply at the (scaled) primary must therefore still drop to fallback — proving the
    ``current_floor == primary`` branch is not defeated by differing Decimal scale.
    """
    recent = frozen_now - timedelta(hours=1)
    _insert_tier1(db_session, 1, qualified_at=recent)
    assert recompute_floor(Decimal("250.00"), settings, db_session) == FALLBACK


def test_current_floor_scaled_fallback_still_matches_fallback(db_session, settings, frozen_now):
    """A current floor of ``Decimal('100.0')`` compares equal to fallback 100 -> can rise to primary."""
    recent = frozen_now - timedelta(hours=1)
    _insert_tier1(db_session, 13, qualified_at=recent)
    assert recompute_floor(Decimal("100.0"), settings, db_session) == PRIMARY


def test_persisted_active_floor_loads_equal_to_primary_decimal(db_session, settings):
    """Persist the active floor as the string ``"250"`` and confirm it loads ``== Decimal('250')``."""
    app_state_set(db_session, "active_budget_floor", "250")
    loaded = load_policy(db_session, settings)
    assert loaded.active_floor == Decimal("250")
    assert loaded.active_floor == Decimal("250.00")  # scale-insensitive equality


def test_persisted_scaled_active_floor_loads_equal_to_primary(db_session, settings, frozen_now):
    """Persist ``"250.00"`` then drive recompute through load -> still recognised as primary."""
    app_state_set(db_session, "active_budget_floor", "250.00")
    recent = frozen_now - timedelta(hours=1)
    _insert_tier1(db_session, 2, qualified_at=recent)
    loaded = load_policy(db_session, settings)
    assert loaded.active_floor == PRIMARY
    # scarce supply -> drop to fallback (branch reached despite the persisted scale)
    assert recompute_floor(loaded.active_floor, settings, db_session) == FALLBACK


# --------------------------------------------------------------------------------------
# recompute_floor — pass-through for a floor that is neither primary nor fallback
# --------------------------------------------------------------------------------------


def test_unknown_current_floor_passes_through_when_scarce(db_session, settings, frozen_now):
    """A current floor that is neither primary nor fallback is returned UNCHANGED (scarce supply)."""
    odd = Decimal("175")
    assert recompute_floor(odd, settings, db_session) == odd


def test_unknown_current_floor_passes_through_when_plentiful(db_session, settings, frozen_now):
    """Same pass-through holds under plentiful supply: neither transition condition can match."""
    odd = Decimal("175")
    recent = frozen_now - timedelta(hours=1)
    _insert_tier1(db_session, 50, qualified_at=recent)
    assert recompute_floor(odd, settings, db_session) == odd


def test_unknown_current_floor_preserves_scale(db_session, settings, frozen_now):
    """The exact object/scale is returned unchanged for a non-matching floor."""
    odd = Decimal("123.45")
    out = recompute_floor(odd, settings, db_session)
    assert out == odd
    assert out is odd  # identity: the function returns current_floor directly


# --------------------------------------------------------------------------------------
# load_policy / save_policy
# --------------------------------------------------------------------------------------


def test_load_policy_default_unset_equals_primary(db_session, settings):
    """With nothing persisted, the loaded floor defaults to the primary floor (250)."""
    assert app_state_get(db_session, "active_budget_floor") is None
    loaded = load_policy(db_session, settings)
    assert loaded.active_floor == PRIMARY
    assert isinstance(loaded, BudgetPolicy)


def test_save_load_round_trips_fallback(db_session, settings):
    """save_policy then load_policy round-trips a fallback value through the app_state string."""
    save_policy(db_session, BudgetPolicy(active_floor=FALLBACK))
    # stored as a plain string
    assert app_state_get(db_session, "active_budget_floor") == "100"
    loaded = load_policy(db_session, settings)
    assert loaded.active_floor == FALLBACK
    assert loaded.active_floor == Decimal("100")


def test_save_load_round_trips_arbitrary_decimal(db_session, settings):
    """A non-primary/non-fallback floor round-trips exactly too."""
    save_policy(db_session, BudgetPolicy(active_floor=Decimal("175")))
    loaded = load_policy(db_session, settings)
    assert loaded.active_floor == Decimal("175")


def test_save_overwrites_existing_active_floor(db_session, settings):
    """A second save updates (does not duplicate) the persisted active floor."""
    save_policy(db_session, BudgetPolicy(active_floor=PRIMARY))
    save_policy(db_session, BudgetPolicy(active_floor=FALLBACK))
    assert app_state_get(db_session, "active_budget_floor") == "100"
    assert load_policy(db_session, settings).active_floor == FALLBACK


def test_save_then_recompute_uses_persisted_floor(db_session, settings, frozen_now):
    """End-to-end: persist fallback, plentiful supply -> recompute rises -> persist primary -> reload."""
    save_policy(db_session, BudgetPolicy(active_floor=FALLBACK))
    recent = frozen_now - timedelta(hours=1)
    _insert_tier1(db_session, 13, qualified_at=recent)
    loaded = load_policy(db_session, settings)
    new_floor = recompute_floor(loaded.active_floor, settings, db_session)
    assert new_floor == PRIMARY
    save_policy(db_session, BudgetPolicy(active_floor=new_floor))
    assert load_policy(db_session, settings).active_floor == PRIMARY


# --------------------------------------------------------------------------------------
# Cross-checks against the live utcnow (no freeze) — guards against accidental drift coupling
# --------------------------------------------------------------------------------------


def test_recent_real_now_supply_counts(db_session, settings):
    """Without freezing, rows qualified just now are well within the window and count normally."""
    recent = utcnow() - timedelta(minutes=1)
    _insert_tier1(db_session, 9, qualified_at=recent)
    assert recompute_floor(PRIMARY, settings, db_session) == FALLBACK


def test_far_future_qualified_at_still_within_window(db_session, settings):
    """A qualified_at in the (near) future is >= since, so it counts (>= comparison, not <=)."""
    future = utcnow() + timedelta(hours=1)
    _insert_tier1(db_session, 10, qualified_at=future)
    # count == target at primary -> held primary (proves future rows are not silently dropped)
    assert recompute_floor(PRIMARY, settings, db_session) == PRIMARY
