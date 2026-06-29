"""Typed access to the ``settings`` table + ``app_state`` (constitution III — config over code).

Every behaviour-affecting value is read here at runtime; nothing is hard-coded in logic.
"""
from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy.orm import Session

from ..db.models import AppState, Setting

# key -> (default_value, value_type). Seeded on first run; edit rows to retune (no redeploy).
DEFAULTS: dict[str, tuple[object, str]] = {
    # scheduling / politeness
    "poll_interval_seconds": (120, "int"),
    "poll_jitter_seconds": (15, "int"),
    "misfire_grace_seconds": (60, "int"),
    "client_refresh_hours": (12, "int"),  # reserved: profile enrichment (see models note)
    "delay_min_seconds": (2.5, "float"),
    "delay_max_seconds": (7.0, "float"),
    "project_to_profile_gap_min": (4.0, "float"),
    "project_to_profile_gap_max": (9.0, "float"),
    "max_fetches_per_cycle": (12, "int"),
    # backoff / circuit breaker
    "retry_base_seconds": (2, "int"),
    "retry_cap_seconds": (60, "int"),
    "max_retries_per_request": (5, "int"),
    "cb_cooldown_minutes": (30, "int"),
    "cb_cooldown_factor": (2, "int"),
    "cb_cooldown_max_minutes": (240, "int"),
    # block / structure-change detection
    "block_body_max_bytes": (30000, "int"),
    "nonempty_body_min_bytes": (50000, "int"),
    "challenge_markers": (
        [
            "just a moment", "cf-chl", "__cf_chl", "cf_chl_opt", "challenges.cloudflare.com",
            "cf-mitigated", "checking your browser", "attention required", "g-recaptcha",
            "recaptcha/api.js", "hcaptcha.com", "h-captcha",
        ],
        "json",
    ),
    "listing_shell_markers": (["project-row", "مشروع"], "json"),
    "empty_state_markers": (["لا توجد", "no results"], "json"),
    # qualification / dynamic budget
    "budget_primary_floor": (250, "int"),
    "budget_fallback_floor": (100, "int"),
    "fallback_target": (10, "int"),
    "fallback_buffer": (2, "int"),
    "fallback_window_hours": (24, "int"),
    "budget_comparison_basis": ("max", "str"),
    "currency_usd_rates": ({"USD": 1.0}, "json"),
    "min_hiring_rate": (0, "float"),  # strictly greater-than
    "max_eval_attempts": (5, "int"),
    "pending_max_age_hours": (24, "int"),
    "baseline_on_first_run": (True, "bool"),
    # presentation / ops
    "owner_timezone": ("Africa/Cairo", "str"),
    "heartbeat_hours": (12, "int"),
    "listing_url": ("https://mostaql.com/projects/development", "str"),
    "category_slug": ("development", "str"),
    # personal pipeline & workspace (Feature 3) — all owner-facing tunables (constitution III)
    "watcher_paused": (False, "bool"),  # /pause·/resume + dashboard toggle; worker skips its cycle when true
    "personal_statuses": (
        [
            {"key": "new", "label": "جديد"},
            {"key": "interested", "label": "مهتم"},
            {"key": "applied", "label": "تقدّمت"},
            {"key": "in_discussion", "label": "قيد النقاش"},
            {"key": "won", "label": "ربح"},
            {"key": "lost", "label": "خسارة"},
            {"key": "expired_missed", "label": "منتهي/فائت"},  # Feature 4 auto-transition target
            {"key": "ignored", "label": "تجاهل"},
        ],
        "json",
    ),  # ordered [{key,label}]; first key is the default, "applied" triggers the applied-date rule
    "upload_max_bytes": (10485760, "int"),  # 10 MB max per uploaded file
    "upload_allowed_types": (["pdf", "docx", "md"], "json"),
    # opportunity scoring (Feature 4) — every value tunable at runtime (constitution III)
    # six component weights (0–1 each; NORMALIZED at runtime, never rejected for sum≠1 — FR-009)
    "score_weight_hiring_rate": (0.35, "float"),
    "score_weight_hire_volume": (0.15, "float"),
    "score_weight_budget": (0.15, "float"),
    "score_weight_competition": (0.20, "float"),
    "score_weight_freshness": (0.10, "float"),
    "score_weight_rating": (0.05, "float"),
    # scoring tuning values
    "score_hiring_baseline": (50.0, "float"),       # neutral hiring-rate baseline for shrinkage
    "score_hiring_shrink_k": (5, "int"),            # pseudo-count (shrinkage strength)
    "score_hire_volume_halfsat": (10, "int"),       # half-saturation for hire count
    "score_budget_cap_usd": (1000, "int"),          # diminishing-returns cap (USD)
    "score_budget_tier2_scale": (0.6, "float"),     # Tier-2 budget down-scale
    "score_competition_halfsat_bids": (15, "int"),  # half-saturation for bid crowdedness
    "score_competition_vel_cap": (3.0, "float"),    # bids/hour at which velocity sub-score = 0
    "score_freshness_halflife_hours": (12.0, "float"),  # freshness decay half-life
    "score_rating_min_reviews": (3, "int"),         # reviews for full rating confidence
    # re-check loop (independent of the fast poll)
    "recheck_interval_seconds": (1800, "int"),      # re-check job cadence
    "recheck_batch_size": (20, "int"),              # max projects re-checked per cycle
    "recheck_min_interval_seconds": (1500, "int"),  # never re-check one project more often than this
    "tracking_grace_hours": (72, "int"),            # keep re-checking this long after close, then stop
    # freshness "still good?" signal thresholds
    "freshness_green_max_bids": (8, "int"),
    "freshness_green_max_age_hours": (12, "int"),
    "freshness_red_min_bids": (20, "int"),
    "freshness_red_min_age_hours": (48, "int"),
    # Telegram + auto-status toggles
    "top_default_count": (5, "int"),                # /top default N
    "auto_status_site_enabled": (True, "bool"),     # auto-sync Mostaql status from the loop
    "auto_status_personal_enabled": (False, "bool"),  # optional Interested→Expired/Missed
    # scraper marker — DOM/text markers for an awarded project (confined to scraper/mostaql.py)
    "awarded_markers": (["label-prj-awarded", "تم الترسية", "مسند"], "json"),
}


def _coerce(value: str, value_type: str):
    if value_type == "int":
        return int(value)
    if value_type == "float":
        return float(value)
    if value_type == "bool":
        return value.strip().lower() in ("1", "true", "yes", "on")
    if value_type == "json":
        return json.loads(value)
    return value


def _serialize(value, value_type: str) -> str:
    if value_type == "json":
        return json.dumps(value, ensure_ascii=False)
    if value_type == "bool":
        return "true" if value else "false"
    return str(value)


class SettingsStore:
    """Reads typed settings; small in-memory cache refreshed per poll cycle."""

    def __init__(self, session: Session):
        self.session = session
        self._cache: dict[str, object] = {}

    def reload(self) -> None:
        rows = self.session.query(Setting).all()
        self._cache = {r.key: _coerce(r.value, r.value_type) for r in rows}

    def get(self, key: str):
        if not self._cache:
            self.reload()
        if key in self._cache:
            return self._cache[key]
        if key in DEFAULTS:
            return DEFAULTS[key][0]
        raise KeyError(f"Unknown setting: {key}")

    def get_int(self, key: str) -> int:
        return int(self.get(key))

    def get_float(self, key: str) -> float:
        return float(self.get(key))

    def get_decimal(self, key: str) -> Decimal:
        return Decimal(str(self.get(key)))

    def get_bool(self, key: str) -> bool:
        v = self.get(key)
        return v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")

    def get_json(self, key: str):
        return self.get(key)

    def get_str(self, key: str) -> str:
        return str(self.get(key))


def seed_defaults(session: Session) -> int:
    """Insert any missing default settings. Idempotent. Returns count inserted."""
    existing = {k for (k,) in session.query(Setting.key).all()}
    inserted = 0
    for key, (value, vtype) in DEFAULTS.items():
        if key not in existing:
            session.add(Setting(key=key, value=_serialize(value, vtype), value_type=vtype))
            inserted += 1
    session.commit()
    return inserted


# --- app_state (mutable runtime state that must survive restarts) ---

def app_state_get(session: Session, key: str, default: str | None = None) -> str | None:
    row = session.get(AppState, key)
    return row.value if row else default


def app_state_set(session: Session, key: str, value: str) -> None:
    row = session.get(AppState, key)
    if row:
        row.value = value
    else:
        session.add(AppState(key=key, value=value))
    session.commit()
