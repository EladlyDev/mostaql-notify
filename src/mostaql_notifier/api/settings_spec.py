"""The editable-settings registry (write contract for PUT /api/settings).

The dashboard exposes these watcher tunables — the original 8 plus the Feature 4 scoring / re-check
loop / freshness / Telegram keys (data-model.md). Every PUT is validated against this registry —
unknown keys, type mismatches, out-of-range values, and the cross-field rule are all refused
*before any write* (all-or-nothing → SC-005). Constraints defend the worker: poll interval ≥ 30 s
protects politeness (constitution II); floors/rates ≥ 0 protect qualification (VII); re-check
intervals ≥ 300 s keep the watch-over-time loop polite. The six ``score_weight_*`` keys accept ANY
non-negative float — they are NORMALIZED at runtime (FR-009) and are never rejected for sum ≠ 1.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SettingSpec:
    key: str
    type: str  # "int" | "float" | "bool"
    min: float | None  # always None for "bool"
    max: float | None  # always None for "bool"
    label: str


# Order is the display order on the settings screen.
EDITABLE_SETTINGS: tuple[SettingSpec, ...] = (
    # --- Feature 1/2 watcher tunables ---
    SettingSpec("poll_interval_seconds", "int", 30, None, "فترة الفحص (ثوانٍ)"),
    SettingSpec("client_refresh_hours", "int", 1, None, "تحديث بيانات العميل (ساعات)"),
    SettingSpec("budget_primary_floor", "int", 0, None, "الحد الأدنى للميزانية — الأساسي (USD)"),
    SettingSpec("budget_fallback_floor", "int", 0, None, "الحد الأدنى للميزانية — الاحتياطي (USD)"),
    SettingSpec("fallback_target", "int", 0, None, "هدف العرض الاحتياطي"),
    SettingSpec("fallback_buffer", "int", 0, None, "هامش الاحتياطي"),
    SettingSpec("fallback_window_hours", "int", 1, None, "نافذة قياس العرض (ساعات)"),
    SettingSpec("min_hiring_rate", "float", 0, 100, "الحد الأدنى لمعدل التوظيف (%)"),
    # --- Feature 4: opportunity-score component weights (non-negative; normalized at runtime) ---
    SettingSpec("score_weight_hiring_rate", "float", 0, None, "وزن معدل التوظيف"),
    SettingSpec("score_weight_hire_volume", "float", 0, None, "وزن حجم التوظيف"),
    SettingSpec("score_weight_budget", "float", 0, None, "وزن الميزانية"),
    SettingSpec("score_weight_competition", "float", 0, None, "وزن المنافسة"),
    SettingSpec("score_weight_freshness", "float", 0, None, "وزن الحداثة"),
    SettingSpec("score_weight_rating", "float", 0, None, "وزن تقييم العميل"),
    # --- Feature 4: scoring tuning values ---
    SettingSpec("score_hiring_baseline", "float", 0, 100, "خط الأساس لمعدل التوظيف"),
    SettingSpec("score_hiring_shrink_k", "int", 0, None, "قوة الانكماش (عدد افتراضي)"),
    SettingSpec("score_hire_volume_halfsat", "int", 1, None, "نصف تشبّع حجم التوظيف"),
    SettingSpec("score_budget_cap_usd", "int", 1, None, "سقف الميزانية (USD)"),
    SettingSpec("score_budget_tier2_scale", "float", 0, 1, "معامل تخفيض ميزانية الفئة 2"),
    SettingSpec("score_competition_halfsat_bids", "int", 1, None, "نصف تشبّع ازدحام العروض"),
    SettingSpec("score_competition_vel_cap", "float", 0.0001, None, "سقف سرعة العروض (عرض/ساعة)"),
    SettingSpec("score_freshness_halflife_hours", "float", 0.0001, None, "نصف عمر تحلل الحداثة (ساعات)"),
    SettingSpec("score_rating_min_reviews", "int", 1, None, "أدنى عدد مراجعات لاكتمال الثقة"),
    # --- Feature 4: re-check loop (watch over time) ---
    SettingSpec("recheck_interval_seconds", "int", 300, None, "فترة إعادة الفحص (ثوانٍ)"),
    SettingSpec("recheck_batch_size", "int", 1, None, "حجم دفعة إعادة الفحص"),
    SettingSpec("recheck_min_interval_seconds", "int", 300, None, "أدنى فاصل لإعادة فحص المشروع (ثوانٍ)"),
    SettingSpec("tracking_grace_hours", "int", 0, None, "مهلة المتابعة بعد الإغلاق (ساعات)"),
    # --- Feature 4: freshness "still good?" thresholds ---
    SettingSpec("freshness_green_max_bids", "int", 0, None, "أقصى عروض لإشارة أخضر"),
    SettingSpec("freshness_green_max_age_hours", "int", 0, None, "أقصى عمر لإشارة أخضر (ساعات)"),
    SettingSpec("freshness_red_min_bids", "int", 1, None, "أدنى عروض لإشارة أحمر"),
    SettingSpec("freshness_red_min_age_hours", "int", 1, None, "أدنى عمر لإشارة أحمر (ساعات)"),
    # --- Feature 4: Telegram default + auto-status toggles ---
    SettingSpec("top_default_count", "int", 1, 20, "عدد المشاريع الافتراضي في /top"),
    SettingSpec("auto_status_site_enabled", "bool", None, None, "مزامنة حالة مستقل تلقائيًا"),
    SettingSpec("auto_status_personal_enabled", "bool", None, None, "نقل تلقائي: مهتم ← منتهي/فائت"),
    # --- Feature 6: analytics & insights thresholds (the str ``analytics_timezone`` is DB-edit
    # only, like ``owner_timezone`` — not registered here). ---
    SettingSpec("analytics_default_range_days", "int", 1, None, "المدى الزمني الافتراضي (أيام)"),
    SettingSpec("analytics_min_support", "int", 1, None, "الحد الأدنى للبيانات قبل إظهار التحليل"),
    SettingSpec("analytics_min_wins_support", "int", 1, None,
                "الحد الأدنى لعدد الصفقات الرابحة قبل نصائح الفوز"),
    SettingSpec("analytics_crowded_bids", "int", 1, None, 'عدد العروض الذي يعتبر "مزدحمًا"'),
    SettingSpec("analytics_early_bids", "int", 1, None, "عدد العروض المبكّر"),
    SettingSpec("analytics_max_tips", "int", 1, 20, "أقصى عدد للنصائح"),
    SettingSpec("analytics_suggested_threshold_keep", "float", 0, 1,
                "نسبة الصفقات الرابحة المحتفظ بها عند اقتراح حد التقييم"),
)

EDITABLE_BY_KEY: dict[str, SettingSpec] = {s.key: s for s in EDITABLE_SETTINGS}
EDITABLE_KEYS: frozenset[str] = frozenset(EDITABLE_BY_KEY)


def _coerce_typed(spec: SettingSpec, value: object) -> int | float | bool:
    """Coerce an incoming value to the spec's type.

    A ``"bool"`` spec accepts ONLY a JSON boolean (``True``/``False``); anything else is refused.
    Numeric specs reject bools (a bool is an int subclass) and coerce to int/float.
    """
    if spec.type == "bool":
        if not isinstance(value, bool):
            raise ValueError("القيمة يجب أن تكون قيمة منطقية (صح/خطأ)")
        return value
    if isinstance(value, bool):  # bool is an int subclass; never acceptable for a numeric key
        raise ValueError("قيمة غير صالحة (نوع غير متوقع)")
    if spec.type == "int":
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("القيمة يجب أن تكون عددًا صحيحًا")
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError("القيمة يجب أن تكون عددًا صحيحًا") from exc
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError("القيمة يجب أن تكون رقمًا") from exc


def validate_updates(
    updates: dict[str, object], current: dict[str, object]
) -> dict[str, int | float | bool]:
    """Validate a partial settings update against the registry.

    ``current`` is the present typed value of every editable key (for cross-field checks).
    Returns the coerced, validated values to persist. Raises ``SettingsValidationError`` with
    per-field messages on any problem — and in that case nothing should be written.
    """
    errors: list[tuple[str, str]] = []
    coerced: dict[str, int | float | bool] = {}

    for key, raw in updates.items():
        spec = EDITABLE_BY_KEY.get(key)
        if spec is None:
            errors.append((key, "مفتاح غير معروف أو غير قابل للتعديل"))
            continue
        try:
            value = _coerce_typed(spec, raw)
        except ValueError as exc:
            errors.append((key, str(exc)))
            continue
        if spec.min is not None and value < spec.min:
            errors.append((key, f"القيمة يجب ألا تقل عن {spec.min:g}"))
            continue
        if spec.max is not None and value > spec.max:
            errors.append((key, f"القيمة يجب ألا تزيد عن {spec.max:g}"))
            continue
        coerced[key] = value

    # Cross-field: budget_fallback_floor ≤ budget_primary_floor, evaluated against the resulting
    # combined state (whichever of the two is in the payload merged over current values).
    if "budget_fallback_floor" in coerced or "budget_primary_floor" in coerced:
        fallback = coerced.get("budget_fallback_floor", current.get("budget_fallback_floor"))
        primary = coerced.get("budget_primary_floor", current.get("budget_primary_floor"))
        if fallback is not None and primary is not None and float(fallback) > float(primary):
            errors.append(
                ("budget_fallback_floor", "يجب ألا يتجاوز الحد الاحتياطي الحد الأساسي")
            )

    if errors:
        raise SettingsValidationError(errors)
    return coerced


class SettingsValidationError(Exception):
    """Raised when a settings update fails validation; carries per-field messages."""

    def __init__(self, errors: list[tuple[str, str]]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {m}" for k, m in errors))
