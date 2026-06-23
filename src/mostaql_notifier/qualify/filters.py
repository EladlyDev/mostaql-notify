"""Qualification rules (constitution: fail-closed, config-over-code).

Pure functions read every threshold from :class:`SettingsStore`; nothing is hard-coded.
Unknown / unparseable inputs disqualify (return ``None`` for the budget basis) rather than
assuming a favourable default.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..config.settings_store import SettingsStore
from ..db.models import Client, Project, ProjectStatus


@dataclass(frozen=True)
class Qualification:
    qualified: bool
    tier: int | None
    reason: str


def exclusion_passes(project: Project, settings: SettingsStore) -> bool:
    """Distinct exclusion stage (pass-through in this feature; rules added here later)."""
    return True


def budget_usd(project: Project, settings: SettingsStore) -> Decimal | None:
    """Convert the project's budget to USD using the configured basis and rates.

    Fail-closed: an unknown currency (``None`` or absent from ``currency_usd_rates``) or a
    missing budget yields ``None`` — we never assume USD.
    """
    basis = settings.get_str("budget_comparison_basis")  # default "max"
    bmin = project.budget_min
    bmax = project.budget_max

    value: Decimal | None
    if basis == "min":
        value = bmin if bmin is not None else bmax
    elif basis == "midpoint":
        if bmin is not None and bmax is not None:
            value = (Decimal(bmin) + Decimal(bmax)) / Decimal(2)
        else:
            value = bmax if bmax is not None else bmin
    else:  # "max" (default)
        value = bmax if bmax is not None else bmin

    if value is None:
        return None

    currency = project.currency
    rates = settings.get_json("currency_usd_rates")
    if currency is None or currency not in rates:
        return None

    return Decimal(value) * Decimal(str(rates[currency]))


def qualify(project: Project, client: Client | None, policy, settings: SettingsStore) -> Qualification:
    """Evaluate all gates; the first failing gate sets ``qualified=False`` with its reason."""
    # (1) client hiring rate strictly greater than threshold (0.0 must FAIL).
    if client is None or client.hiring_rate is None:
        return Qualification(False, None, "client_hiring_rate_unknown")
    if not client.hiring_rate > settings.get_float("min_hiring_rate"):
        return Qualification(False, None, "client_hiring_rate_below_min")

    # (2) budget in USD meets the active floor.
    usd = budget_usd(project, settings)
    if usd is None:
        return Qualification(False, None, "budget_unknown")
    if usd < policy.active_floor:
        return Qualification(False, None, "budget_below_floor")

    # (3) project must be open and in the watched category.
    if project.site_status != ProjectStatus.open:
        return Qualification(False, None, "project_not_open")
    if project.category != settings.get_str("category_slug"):
        return Qualification(False, None, "wrong_category")

    # (4) exclusion stage.
    if not exclusion_passes(project, settings):
        return Qualification(False, None, "excluded")

    primary = settings.get_decimal("budget_primary_floor")
    tier = 1 if usd >= primary else 2
    return Qualification(True, tier, "qualified")
