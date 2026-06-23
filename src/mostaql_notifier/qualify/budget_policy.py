"""Dynamic budget floor with hysteresis (config-over-code; no flapping).

The active floor is persisted in ``app_state`` so it survives restarts. ``recompute_floor``
flips between the primary and fallback floors only when the recent tier-1 supply crosses a
threshold, with a dead-band (buffer) to prevent oscillation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from ..config.settings_store import SettingsStore, app_state_get, app_state_set
from ..db.models import Project
from ..db.types import utcnow

_FLOOR_KEY = "active_budget_floor"


@dataclass
class BudgetPolicy:
    active_floor: Decimal


def recompute_floor(current_floor: Decimal, settings: SettingsStore, session: Session) -> Decimal:
    """Return the (possibly unchanged) floor based on recent tier-1 supply.

    Dead-band: only ``primary -> fallback`` (when supply is scarce) and ``fallback -> primary``
    (when supply is plentiful, beyond ``target + buffer``) transitions occur; everything else is
    held to avoid flapping.
    """
    window_hours = settings.get_int("fallback_window_hours")
    since = utcnow() - timedelta(hours=window_hours)
    count = (
        session.query(Project)
        .filter(Project.tier == 1, Project.qualified_at >= since)
        .count()
    )

    primary = Decimal(settings.get_decimal("budget_primary_floor"))
    fallback = Decimal(settings.get_decimal("budget_fallback_floor"))
    target = settings.get_int("fallback_target")
    buffer = settings.get_int("fallback_buffer")

    if current_floor == primary and count < target:
        return fallback
    if current_floor == fallback and count > target + buffer:
        return primary
    return current_floor


def load_policy(session: Session, settings: SettingsStore) -> BudgetPolicy:
    """Load the persisted active floor, defaulting to the primary floor when unset."""
    raw = app_state_get(session, _FLOOR_KEY)
    if raw is None:
        floor = Decimal(settings.get_decimal("budget_primary_floor"))
    else:
        floor = Decimal(raw)
    return BudgetPolicy(active_floor=floor)


def save_policy(session: Session, policy: BudgetPolicy) -> None:
    """Persist the active floor as a string in ``app_state``."""
    app_state_set(session, _FLOOR_KEY, str(policy.active_floor))
