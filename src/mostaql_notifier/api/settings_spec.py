"""The editable-settings registry (write contract for PUT /api/settings).

The dashboard exposes EXACTLY these 8 watcher tunables (data-model.md). Every PUT is validated
against this registry — unknown keys, type mismatches, out-of-range values, and the cross-field
rule are all refused *before any write* (all-or-nothing → SC-005). Constraints defend the worker:
poll interval ≥ 30 s protects politeness (constitution II); floors/rates ≥ 0 protect
qualification (VII).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SettingSpec:
    key: str
    type: str  # "int" | "float"
    min: float | None
    max: float | None
    label: str


# Order is the display order on the settings screen.
EDITABLE_SETTINGS: tuple[SettingSpec, ...] = (
    SettingSpec("poll_interval_seconds", "int", 30, None, "فترة الفحص (ثوانٍ)"),
    SettingSpec("client_refresh_hours", "int", 1, None, "تحديث بيانات العميل (ساعات)"),
    SettingSpec("budget_primary_floor", "int", 0, None, "الحد الأدنى للميزانية — الأساسي (USD)"),
    SettingSpec("budget_fallback_floor", "int", 0, None, "الحد الأدنى للميزانية — الاحتياطي (USD)"),
    SettingSpec("fallback_target", "int", 0, None, "هدف العرض الاحتياطي"),
    SettingSpec("fallback_buffer", "int", 0, None, "هامش الاحتياطي"),
    SettingSpec("fallback_window_hours", "int", 1, None, "نافذة قياس العرض (ساعات)"),
    SettingSpec("min_hiring_rate", "float", 0, 100, "الحد الأدنى لمعدل التوظيف (%)"),
)

EDITABLE_BY_KEY: dict[str, SettingSpec] = {s.key: s for s in EDITABLE_SETTINGS}
EDITABLE_KEYS: frozenset[str] = frozenset(EDITABLE_BY_KEY)


def _coerce_typed(spec: SettingSpec, value: object) -> int | float:
    """Coerce an incoming value to the spec's type, rejecting bools and non-numerics."""
    if isinstance(value, bool):  # bool is an int subclass; never acceptable here
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


def validate_updates(updates: dict[str, object], current: dict[str, object]) -> dict[str, int | float]:
    """Validate a partial settings update against the registry.

    ``current`` is the present typed value of every editable key (for cross-field checks).
    Returns the coerced, validated values to persist. Raises ``SettingsValidationError`` with
    per-field messages on any problem — and in that case nothing should be written.
    """
    errors: list[tuple[str, str]] = []
    coerced: dict[str, int | float] = {}

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
