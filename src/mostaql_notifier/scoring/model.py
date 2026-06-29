"""PURE opportunity-scoring model (Feature 4, Part A) — see contracts/scoring-model.md.

``score_project`` is deterministic in its arguments: no network, no DB, no clock read (``now_utc`` is
injected), reading only already-materialized attributes off ``project``, ``client`` and the
eager-loaded ``project.snapshots`` trajectory. Every constant is a ``settings`` key (Config-over-Code).
The six components each return a sub-score in [0, 1]; the final score is
``100 × Σ(normalized_weightᵢ × sub_scoreᵢ)`` and the breakdown dict is persisted verbatim to
``project_scores.breakdown``.

Implements T013 per contracts/scoring-model.md §2 (weight normalization), §3 (the six components)
and §4 (the stored breakdown shape).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timezone
from decimal import Decimal

from ..qualify.filters import budget_usd as _budget_usd

# A small positive guard so a zero-duration snapshot window never divides by zero.
_EPS = 1e-9

# Component order, key and Arabic (RTL) label per contract §4.
_COMPONENTS = (
    ("hiring_rate", "معدل التوظيف"),
    ("hire_volume", "حجم التوظيف"),
    ("budget", "الميزانية"),
    ("competition", "المنافسة"),
    ("freshness", "الحداثة"),
    ("rating", "تقييم العميل"),
)

# Configured-weight settings keys, in component order.
_WEIGHT_KEYS = (
    "score_weight_hiring_rate",
    "score_weight_hire_volume",
    "score_weight_budget",
    "score_weight_competition",
    "score_weight_freshness",
    "score_weight_rating",
)


@dataclass(frozen=True)
class ScoreResult:
    """The pure scorer's output: the 0–100 score and the breakdown dict (persisted verbatim)."""

    score: float
    breakdown: dict


def score_project(project, client, *, settings, now_utc) -> ScoreResult:
    """Compute the 0–100 opportunity score + breakdown for one (already-loaded) project.

    Pure and total: never raises for a loaded project; a missing input contributes the component's
    documented floor. ``settings`` is a ``SettingsStore``; ``now_utc`` is an aware-UTC datetime.

    See contracts/scoring-model.md §3 (six components), §2 (weight normalization) and §4 (shape).
    """
    now_utc = _ensure_utc(now_utc)
    age_hours = _age_hours(project, now_utc)

    sub_a, raw_a, in_a = _hiring_rate(client, settings)
    sub_b, raw_b, in_b = _hire_volume(client, settings)
    sub_c, raw_c, in_c = _budget(project, settings)
    sub_d, raw_d, in_d = _competition(project, settings, age_hours)
    sub_e, raw_e, in_e = _freshness(settings, age_hours)
    sub_f, raw_f, in_f = _rating(client, settings)

    subs = [sub_a, sub_b, sub_c, sub_d, sub_e, sub_f]
    raws = [raw_a, raw_b, raw_c, raw_d, raw_e, raw_f]

    # §2 — weight normalization. Settings validation rejects negatives/NaN upstream; sanitize anyway.
    configured = [settings.get_float(k) for k in _WEIGHT_KEYS]
    configured = [w if (math.isfinite(w) and w >= 0.0) else 0.0 for w in configured]
    total_w = math.fsum(configured)
    if total_w > 0.0:
        normalized_weights = [w / total_w for w in configured]
    else:  # all-zero ⇒ equal fallback across the six
        normalized_weights = [1.0 / 6.0] * 6
    normalized_flag = abs(total_w - 1.0) > 1e-9

    raw_score = 100.0 * math.fsum(nw * s for nw, s in zip(normalized_weights, subs, strict=True))
    if not math.isfinite(raw_score):
        raw_score = 0.0
    raw_score = max(0.0, min(100.0, raw_score))

    components = []
    for (key, label), sub, raw, nw in zip(_COMPONENTS, subs, raws, normalized_weights, strict=True):
        contribution = 100.0 * nw * sub
        components.append(
            {
                "key": key,
                "label": label,
                "raw": _num(raw),
                "sub_score": round(sub, 4),
                "weight": round(nw, 6),
                "contribution": round(contribution, 2),
            }
        )

    inputs = {
        "hiring_rate": _num(raw_a),
        "projects_posted": in_a["projects_posted"],
        "hiring_rate_adjusted": in_a["hiring_rate_adjusted"],
        "hires_count": in_b["hires_count"],
        "budget_usd": in_c["budget_usd"],
        "tier": in_c["tier"],
        "bids_count": in_d["bids_count"],
        "posted_at": _iso(getattr(project, "posted_at", None)),
        "age_hours": in_e["age_hours"],
        "avg_rating": _num(raw_f),
        "reviews_count": in_f["reviews_count"],
        "snapshot_count": in_d["snapshot_count"],
        "velocity_bph": in_d["velocity_bph"],
        "velocity_source": in_d["velocity_source"],
    }

    breakdown = {
        "score": round(raw_score, 2),
        "normalized": normalized_flag,
        "computed_at": _iso(now_utc),
        "components": components,
        "weights": {
            "configured": dict(zip(_keys(), [round(w, 6) for w in configured], strict=True)),
            "sum": round(total_w, 6),
            "normalized": dict(
                zip(_keys(), [round(nw, 6) for nw in normalized_weights], strict=True)
            ),
        },
        "inputs": inputs,
    }
    return ScoreResult(score=raw_score, breakdown=breakdown)


# --------------------------------------------------------------------------- components


def _hiring_rate(client, settings):
    """(a) Confidence-shrunk hiring rate — §3(a). Floor: baseline/100 (neutral 0.5 at defaults)."""
    baseline = settings.get_float("score_hiring_baseline")
    k = settings.get_int("score_hiring_shrink_k")
    raw = _cval(client, "hiring_rate")
    r = raw if raw is not None else baseline
    n = _cval(client, "projects_posted")
    n = n if n is not None else 0
    denom = n + k
    r_adj = (r * n + baseline * k) / denom if denom > 0 else baseline
    sub = _finalize(r_adj / 100.0, baseline / 100.0)
    return sub, raw, {
        "projects_posted": n,
        "hiring_rate_adjusted": round(r_adj, 2) if math.isfinite(r_adj) else None,
    }


def _hire_volume(client, settings):
    """(b) Diminishing-returns hire volume — §3(b). Floor: 0.0."""
    s = settings.get_int("score_hire_volume_halfsat")
    raw = _cval(client, "hires_count")
    h = raw if raw is not None else 0
    denom = h + s
    sub = _finalize(h / denom if denom > 0 else 0.0, 0.0)
    return sub, raw, {"hires_count": h}


def _budget(project, settings):
    """(c) Budget to a cap, Tier-2 down-scale — §3(c). Budget basis reused from qualify.filters."""
    usd_dec = _budget_usd(project, settings)
    usd = float(usd_dec) if usd_dec is not None else 0.0
    cap = settings.get_int("score_budget_cap_usd")
    sub = min(usd, cap) / cap if cap > 0 else 0.0
    tier = getattr(project, "tier", None)
    if tier == 2:
        sub = sub * settings.get_float("score_budget_tier2_scale")
    sub = _finalize(sub, 0.0)
    raw = usd if usd_dec is not None else None
    return sub, raw, {
        "budget_usd": round(usd, 4) if usd_dec is not None else None,
        "tier": tier,
    }


def _competition(project, settings, age_hours):
    """(d) Crowdedness × velocity — §3(d). Floor: 1.0 (unknown bids ⇒ uncrowded)."""
    halfsat = settings.get_int("score_competition_halfsat_bids")
    vel_cap = settings.get_float("score_competition_vel_cap")
    raw = getattr(project, "bids_count", None)
    bids = raw if raw is not None else 0
    crowd_denom = bids + halfsat
    crowd = 1.0 - (bids / crowd_denom if crowd_denom > 0 else 0.0)

    snaps = list(getattr(project, "snapshots", None) or [])
    if len(snaps) >= 2:
        earliest, latest = snaps[0], snaps[-1]
        e_bids = getattr(earliest, "bids_count", None) or 0
        l_bids = getattr(latest, "bids_count", None) or 0
        delta_bids = max(l_bids - e_bids, 0)
        delta_hours = max(
            (latest.captured_at - earliest.captured_at).total_seconds() / 3600.0, _EPS
        )
        velocity = delta_bids / delta_hours
        source = "trajectory"
    else:  # first re-check — no prior snapshot to diff against
        velocity = bids / max(age_hours, 1.0)
        source = "current_over_age"

    vel = 1.0 - min(velocity / vel_cap, 1.0) if vel_cap > 0 else 0.0
    sub = _finalize((crowd + vel) / 2.0, 1.0)
    return sub, raw, {
        "bids_count": bids,
        "snapshot_count": len(snaps),
        "velocity_bph": round(velocity, 4) if math.isfinite(velocity) else None,
        "velocity_source": source,
    }


def _freshness(settings, age_hours):
    """(e) Exponential age decay — §3(e). Floor: 1.0 (newest). ``raw`` is the age in hours."""
    half_life = settings.get_float("score_freshness_halflife_hours")
    sub = 0.5 ** (age_hours / half_life) if half_life > 0 else 1.0
    sub = _finalize(sub, 1.0)
    age_round = round(age_hours, 4)
    return sub, age_round, {"age_hours": age_round}


def _rating(client, settings):
    """(f) Small signed nudge by review confidence — §3(f). Floor: 0.5 (neutral)."""
    min_reviews = settings.get_int("score_rating_min_reviews")
    raw = _cval(client, "avg_rating")
    rating = raw if raw is not None else 3.0
    reviews = _cval(client, "reviews_count")
    reviews = reviews if reviews is not None else 0
    confidence = min(reviews / min_reviews, 1.0) if min_reviews > 0 else 1.0
    sub = 0.5 + ((rating - 3.0) / 2.0) * confidence * 0.5
    sub = _finalize(sub, 0.5)
    return sub, raw, {"reviews_count": reviews}


# --------------------------------------------------------------------------- helpers


def _keys() -> list[str]:
    return [key for key, _label in _COMPONENTS]


def _cval(obj, name):
    """Read ``obj.name`` or ``None`` when ``obj`` (e.g. a client) is absent."""
    return getattr(obj, name, None) if obj is not None else None


def _finalize(sub: float, floor: float) -> float:
    """Guard NaN/inf to the component floor, then clamp into [0, 1]."""
    if not math.isfinite(sub):
        sub = floor
    return max(0.0, min(1.0, sub))


def _age_hours(project, now_utc) -> float:
    """Project age in hours from ``posted_at`` ⇒ fallback ``scraped_at``; clamped ≥ 0 (§3e)."""
    basis = getattr(project, "posted_at", None)
    if basis is None:
        basis = getattr(project, "scraped_at", None)
    if basis is None:  # structurally impossible (scraped_at is NOT NULL); never raise
        return 0.0
    age = (now_utc - _ensure_utc(basis)).total_seconds() / 3600.0
    return max(age, 0.0)


def _num(value):
    """JSON-friendly number echo: ``Decimal`` ⇒ ``float``; ``None``/``int``/``float`` pass through."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _iso(dt):
    """ISO-8601 UTC string with a trailing ``Z`` (matching the contract examples), or ``None``."""
    if dt is None:
        return None
    return _ensure_utc(dt).isoformat().replace("+00:00", "Z")


def _ensure_utc(dt):
    """Coerce to aware UTC (naive ⇒ assume UTC); all datetimes in this project are UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
