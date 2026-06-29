"""PURE freshness "still good?" deriver (Feature 4, Part C-1) — see contracts/scoring-model.md §5.

Derives a coarse, action-oriented green/yellow/red traffic light from the project's latest
observation (status + bids + age) against configured thresholds. Derived on read (never stored),
distinct from the smooth freshness *component* of the score. Pure: no I/O, ``now_utc`` injected.

NOTE: the skeleton pinned the public contract (T001). This is the full logic (T035).
"""
from __future__ import annotations

# A project in any of these states always reads red, regardless of its last score (§5, US3-3).
_RED_STATUSES = frozenset({"closed", "awarded", "unknown"})


def _status_value(status) -> str:
    """Normalize a ``ProjectStatus`` enum (a ``str`` subclass), a plain string, or ``None`` to a
    lower-cased ``.value`` string. Never raises."""
    if status is None:
        return ""
    # ProjectStatus members carry ``.value``; a bare string falls back to itself.
    value = getattr(status, "value", status)
    return str(value).strip().lower()


def _age_hours(project, now_utc) -> float:
    """``(now_utc − posted_at)`` in hours, falling back to ``scraped_at`` (NOT NULL) when
    ``posted_at`` is missing; clamped at ``0`` against clock skew / a future timestamp (§3e). Never
    raises — any unusable basis degrades to ``0``."""
    basis = getattr(project, "posted_at", None)
    if basis is None:
        basis = getattr(project, "scraped_at", None)
    if basis is None:
        return 0.0
    try:
        seconds = (now_utc - basis).total_seconds()
    except (TypeError, ValueError):
        return 0.0
    return max(seconds / 3600.0, 0.0)


def freshness(project, latest_snapshot, *, settings, now_utc) -> str:
    """Return ``"green"`` | ``"yellow"`` | ``"red"`` for one project.

    Inputs come from ``latest_snapshot`` when given (else the project's own ``site_status`` /
    ``bids_count``); age from ``posted_at`` falling back to ``scraped_at``. Evaluated red → green →
    else yellow (red wins); degrades gracefully with a single snapshot and never errors (§5).
    """
    # Source status + bids from the latest snapshot when one is supplied, else from the project.
    source = latest_snapshot if latest_snapshot is not None else project
    status = _status_value(getattr(source, "site_status", None))
    bids = getattr(source, "bids_count", None)
    bids = 0 if bids is None else bids
    age_hours = _age_hours(project, now_utc)

    green_max_bids = settings.get_int("freshness_green_max_bids")
    green_max_age_hours = settings.get_int("freshness_green_max_age_hours")
    red_min_bids = settings.get_int("freshness_red_min_bids")
    red_min_age_hours = settings.get_int("freshness_red_min_age_hours")

    # red wins: a closed/awarded/unknown project, a crowded one, or an aged-out one.
    if (
        status in _RED_STATUSES
        or bids >= red_min_bids
        or age_hours >= red_min_age_hours
    ):
        return "red"
    # green: still open, few bids, still fresh.
    if (
        status == "open"
        and bids <= green_max_bids
        and age_hours <= green_max_age_hours
    ):
        return "green"
    # yellow otherwise — cooling: aging and/or bids climbing, still open.
    return "yellow"
