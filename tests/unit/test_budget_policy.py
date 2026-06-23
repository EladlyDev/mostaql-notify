"""Unit tests for the dynamic budget floor (hysteresis + persistence)."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from mostaql_notifier.db.models import EvalStatus, Project, ProjectStatus
from mostaql_notifier.db.types import utcnow
from mostaql_notifier.qualify.budget_policy import (
    BudgetPolicy,
    load_policy,
    recompute_floor,
    save_policy,
)


def _insert_tier1(db_session, n, *, age_hours=1.0):
    when = utcnow() - timedelta(hours=age_hours)
    for i in range(n):
        db_session.add(
            Project(
                mostaql_id=f"t1-{age_hours}-{i}",
                scraped_at=utcnow(),
                site_status=ProjectStatus.open,
                eval_status=EvalStatus.qualified,
                tier=1,
                qualified_at=when,
                raw={},
            )
        )
    db_session.commit()


def test_primary_drops_to_fallback_when_supply_scarce(db_session, settings):
    # default target=10; insert fewer than target -> drop to fallback (100).
    _insert_tier1(db_session, 3)
    new = recompute_floor(Decimal(250), settings, db_session)
    assert new == Decimal(100)


def test_fallback_rises_to_primary_when_supply_plentiful(db_session, settings):
    # default target=10, buffer=2 -> need count > 12 to rise.
    _insert_tier1(db_session, 13)
    new = recompute_floor(Decimal(100), settings, db_session)
    assert new == Decimal(250)


def test_dead_band_holds_fallback(db_session, settings):
    # count between target and target+buffer: fallback stays fallback (no flapping).
    _insert_tier1(db_session, 11)
    new = recompute_floor(Decimal(100), settings, db_session)
    assert new == Decimal(100)


def test_dead_band_holds_primary(db_session, settings):
    # plentiful supply while at primary: stays primary.
    _insert_tier1(db_session, 13)
    new = recompute_floor(Decimal(250), settings, db_session)
    assert new == Decimal(250)


def test_old_tier1_outside_window_excluded(db_session, settings):
    # 13 recent qualifications, but aged beyond the window -> treated as scarce supply.
    _insert_tier1(db_session, 13, age_hours=48.0)
    new = recompute_floor(Decimal(250), settings, db_session)
    assert new == Decimal(100)


def test_save_load_round_trip(db_session, settings):
    save_policy(db_session, BudgetPolicy(active_floor=Decimal(175)))
    loaded = load_policy(db_session, settings)
    assert loaded.active_floor == Decimal(175)


def test_load_defaults_to_primary(db_session, settings):
    loaded = load_policy(db_session, settings)
    assert loaded.active_floor == Decimal(250)
