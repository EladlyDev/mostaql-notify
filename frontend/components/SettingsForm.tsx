"use client";

import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, AlertTriangle, RotateCcw, Save } from "lucide-react";

import { ApiError, updateSettings } from "@/lib/api";
import type {
  SettingItem,
  SettingsResponse,
  SettingsValidationError,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { Bidi } from "@/components/Bidi";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

// Logical grouping of the known setting keys into sensible sections.
// Any key the backend returns that is not listed here falls into "أخرى".
const GROUPS: { id: string; title: string; description: string; keys: string[] }[] =
  [
    {
      id: "scheduling",
      title: "الجدولة",
      description: "معدل الفحص وتحديث بيانات العملاء.",
      keys: ["poll_interval_seconds", "client_refresh_hours"],
    },
    {
      id: "budget",
      title: "الميزانية",
      description: "الحدود الدنيا للميزانية الأساسية والاحتياطية.",
      keys: ["budget_primary_floor", "budget_fallback_floor"],
    },
    {
      id: "fallback",
      title: "الوضع الاحتياطي",
      description: "إعدادات النافذة والهدف للوضع الاحتياطي.",
      keys: [
        "fallback_target",
        "fallback_buffer",
        "fallback_window_hours",
      ],
    },
    {
      id: "qualification",
      title: "التأهيل",
      description: "معايير تأهيل العملاء.",
      keys: ["min_hiring_rate"],
    },
    {
      id: "scoring",
      title: "التقييم",
      description:
        "أوزان ومعاملات احتساب درجة الفرصة، وحلقة إعادة الفحص، وعتبات الحداثة.",
      keys: [
        // Scoring weights (normalized at runtime — not required to sum to 1).
        "score_weight_hiring_rate",
        "score_weight_hire_volume",
        "score_weight_budget",
        "score_weight_competition",
        "score_weight_freshness",
        "score_weight_rating",
        // Scoring tuning values.
        "score_hiring_baseline",
        "score_hiring_shrink_k",
        "score_hire_volume_halfsat",
        "score_budget_cap_usd",
        "score_budget_tier2_scale",
        "score_competition_halfsat_bids",
        "score_competition_vel_cap",
        "score_freshness_halflife_hours",
        "score_rating_min_reviews",
        // Re-check loop.
        "recheck_interval_seconds",
        "recheck_batch_size",
        "recheck_min_interval_seconds",
        "tracking_grace_hours",
        // Freshness thresholds.
        "freshness_green_max_bids",
        "freshness_green_max_age_hours",
        "freshness_red_min_bids",
        "freshness_red_min_age_hours",
        // Telegram.
        "top_default_count",
      ],
    },
    {
      id: "automation",
      title: "الأتمتة",
      description: "مزامنة الحالة تلقائيًا من حلقة المتابعة.",
      keys: ["auto_status_site_enabled", "auto_status_personal_enabled"],
    },
    {
      id: "analytics",
      title: "التحليلات",
      description:
        "عتبات قسم التحليلات والنصائح (تُطبَّق عند التحديث التالي، بلا إعادة احتساب).",
      keys: [
        "analytics_default_range_days",
        "analytics_min_support",
        "analytics_min_wins_support",
        "analytics_crowded_bids",
        "analytics_early_bids",
        "analytics_max_tips",
        "analytics_suggested_threshold_keep",
      ],
    },
  ];

// Short Arabic helper/unit text keyed by setting key. Optional — absent keys
// simply render without a hint.
const HINTS: Record<string, string> = {
  poll_interval_seconds: "بالثواني — الحد الأدنى ٣٠ ثانية.",
  client_refresh_hours: "بالساعات.",
  budget_primary_floor: "الحد الأدنى للميزانية الأساسية.",
  budget_fallback_floor:
    "يجب ألّا يتجاوز الحد الأدنى للميزانية الأساسية.",
  fallback_target: "عدد المشاريع المستهدف في النافذة.",
  fallback_buffer: "هامش إضافي فوق الهدف.",
  fallback_window_hours: "طول النافذة بالساعات.",
  min_hiring_rate: "نسبة مئوية بين ٠ و ١٠٠.",
  // Scoring weights — relative أوزان (تُطبَّع تلقائيًا، لا يلزم أن يكون مجموعها ١).
  score_weight_hiring_rate: "وزن نسبي — يُطبَّع تلقائيًا.",
  score_weight_hire_volume: "وزن نسبي — يُطبَّع تلقائيًا.",
  score_weight_budget: "وزن نسبي — يُطبَّع تلقائيًا.",
  score_weight_competition: "وزن نسبي — يُطبَّع تلقائيًا.",
  score_weight_freshness: "وزن نسبي — يُطبَّع تلقائيًا.",
  score_weight_rating: "وزن نسبي — يُطبَّع تلقائيًا.",
  // Scoring tuning.
  score_hiring_baseline: "خط الأساس المحايد لنسبة التوظيف (٠–١٠٠).",
  score_hiring_shrink_k: "قوة التنعيم (عدد افتراضي ≥ ٠).",
  score_hire_volume_halfsat: "نقطة نصف التشبّع لعدد التوظيفات (≥ ١).",
  score_budget_cap_usd: "سقف تناقص العائد بالدولار (≥ ١).",
  score_budget_tier2_scale: "تخفيض ميزانية المستوى الثاني (٠–١).",
  score_competition_halfsat_bids: "نصف التشبّع لازدحام العروض (≥ ١).",
  score_competition_vel_cap: "سرعة العروض/الساعة عند درجة صفر (> ٠).",
  score_freshness_halflife_hours: "نصف عمر تضاؤل الحداثة بالساعات (> ٠).",
  score_rating_min_reviews: "عدد المراجعات للثقة الكاملة (≥ ١).",
  // Re-check loop.
  recheck_interval_seconds: "بالثواني — الحد الأدنى ٣٠٠.",
  recheck_batch_size: "أقصى عدد مشاريع لكل دورة (≥ ١).",
  recheck_min_interval_seconds: "أقل فاصل لإعادة فحص المشروع نفسه (≥ ٣٠٠ ثانية).",
  tracking_grace_hours: "مدة المتابعة بعد الإغلاق بالساعات (≥ ٠).",
  // Freshness thresholds.
  freshness_green_max_bids: "أقصى عدد عروض لإشارة «حديث» الخضراء.",
  freshness_green_max_age_hours: "أقصى عمر بالساعات لإشارة «حديث» الخضراء.",
  freshness_red_min_bids: "أدنى عدد عروض لإشارة «قديم» الحمراء.",
  freshness_red_min_age_hours: "أدنى عمر بالساعات لإشارة «قديم» الحمراء.",
  // Telegram + toggles.
  top_default_count: "عدد المشاريع الافتراضي لأمر /top (١–٢٠).",
  auto_status_site_enabled: "مزامنة حالة مستقل تلقائيًا من حلقة المتابعة.",
  auto_status_personal_enabled: "تحويل «مهتم» إلى «منتهي/فائت» تلقائيًا عند الإغلاق.",
  // Analytics thresholds.
  analytics_default_range_days: "المدى الزمني الافتراضي للتحليلات بالأيام.",
  analytics_min_support: "أقل عدد من السجلات قبل إظهار تحليل أو نصيحة.",
  analytics_min_wins_support: "أقل عدد من الصفقات الرابحة قبل ظهور نصائح الفوز.",
  analytics_crowded_bids: "عدد العروض الذي يُعتبر عنده المشروع «مزدحمًا».",
  analytics_early_bids: "عدد العروض «المبكّر» الذي تشير إليه نصيحة سرعة التقديم.",
  analytics_max_tips: "أقصى عدد من النصائح المعروضة (١–٢٠).",
  analytics_suggested_threshold_keep:
    "نسبة الصفقات الرابحة التي يحتفظ بها حدّ التقييم المقترح (٠–١).",
};

type FieldErrors = Record<string, string>;

// String form values keyed by setting key (inputs are controlled as strings
// so partial edits / empty fields don't get coerced prematurely).
type FormValues = Record<string, string>;

function itemsToValues(items: SettingItem[]): FormValues {
  const out: FormValues = {};
  for (const it of items) out[it.key] = String(it.value);
  return out;
}

function step(type: SettingItem["type"]): string {
  return type === "float" ? "0.1" : "1";
}

/** Soft client-side validation for one field. Returns an Arabic message or null. */
function validateField(item: SettingItem, raw: string): string | null {
  // Boolean toggles are always valid ("true"/"false") — no numeric checks.
  if (item.type === "bool") return null;
  const trimmed = raw.trim();
  if (trimmed === "") return "هذا الحقل مطلوب.";
  const n = Number(trimmed);
  if (!Number.isFinite(n)) return "أدخل رقمًا صحيحًا.";
  if (item.type === "int" && !Number.isInteger(n)) {
    return "يجب أن تكون القيمة عددًا صحيحًا.";
  }
  if (item.min != null && n < item.min) {
    return `يجب ألّا تقل القيمة عن ${item.min}.`;
  }
  if (item.max != null && n > item.max) {
    return `يجب ألّا تزيد القيمة عن ${item.max}.`;
  }
  return null;
}

function isValidationBody(
  body: unknown
): body is SettingsValidationError {
  return (
    !!body &&
    typeof body === "object" &&
    "errors" in body &&
    Array.isArray((body as { errors: unknown }).errors)
  );
}

export function SettingsForm({
  data,
  onSaved,
}: {
  data: SettingsResponse;
  onSaved: (next: SettingsResponse) => void;
}) {
  const items = data.items;
  const loaded = useMemo(() => itemsToValues(items), [items]);

  const [values, setValues] = useState<FormValues>(loaded);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [savedFlash, setSavedFlash] = useState(false);
  const [generalError, setGeneralError] = useState<string | null>(null);

  const byKey = useMemo(() => {
    const m = new Map<string, SettingItem>();
    for (const it of items) m.set(it.key, it);
    return m;
  }, [items]);

  // Keys whose current value differs from the loaded (server) value.
  const changedKeys = useMemo(
    () => items.filter((it) => values[it.key] !== loaded[it.key]).map((it) => it.key),
    [items, values, loaded]
  );
  const dirty = changedKeys.length > 0;

  const mutation = useMutation({
    mutationFn: (patch: Record<string, number | boolean>) =>
      // `updateSettings` is typed numeric-only; booleans serialize to JSON
      // booleans, which the registry accepts for `bool` keys.
      updateSettings(patch as Record<string, number>),
    onSuccess: (next) => {
      setFieldErrors({});
      setGeneralError(null);
      setValues(itemsToValues(next.items));
      setSavedFlash(true);
      onSaved(next);
      window.setTimeout(() => setSavedFlash(false), 4000);
    },
    onError: (err) => {
      setSavedFlash(false);
      if (err instanceof ApiError && err.isValidationError) {
        if (isValidationBody(err.body)) {
          const mapped: FieldErrors = {};
          for (const e of err.body.errors) mapped[e.key] = e.message;
          setFieldErrors(mapped);
          setGeneralError(
            "تعذّر الحفظ بسبب أخطاء في القيم. لم يتم حفظ أي تغييرات."
          );
          return;
        }
      }
      setFieldErrors({});
      if (err instanceof ApiError && err.isNetworkError) {
        setGeneralError(
          "تعذّر الاتصال بالخادم. لم يتم حفظ التغييرات؛ القيم محفوظة محليًا، حاول مجددًا."
        );
        return;
      }
      const msg =
        err instanceof Error ? err.message : "حدث خطأ غير متوقع أثناء الحفظ.";
      setGeneralError(msg);
    },
  });

  function setValue(key: string, raw: string) {
    setValues((v) => ({ ...v, [key]: raw }));
    setSavedFlash(false);
    // Clear a server/soft error for this field as soon as it is edited.
    setFieldErrors((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }

  function handleReset() {
    setValues(loaded);
    setFieldErrors({});
    setGeneralError(null);
    setSavedFlash(false);
    mutation.reset();
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSavedFlash(false);
    setGeneralError(null);

    // Soft-validate only the changed fields; server remains source of truth.
    const softErrors: FieldErrors = {};
    for (const key of changedKeys) {
      const item = byKey.get(key);
      if (!item) continue;
      const msg = validateField(item, values[key]);
      if (msg) softErrors[key] = msg;
    }
    if (Object.keys(softErrors).length > 0) {
      setFieldErrors(softErrors);
      setGeneralError("راجع القيم المميّزة قبل الحفظ.");
      return;
    }
    setFieldErrors({});

    const patch: Record<string, number | boolean> = {};
    for (const key of changedKeys) {
      const item = byKey.get(key);
      patch[key] =
        item?.type === "bool"
          ? values[key] === "true"
          : Number(values[key].trim());
    }
    mutation.mutate(patch);
  }

  const saving = mutation.isPending;

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-6">
      {GROUPS.map((group) => {
        const groupItems = group.keys
          .map((k) => byKey.get(k))
          .filter((it): it is SettingItem => it != null);
        if (groupItems.length === 0) return null;
        return (
          <Card key={group.id}>
            <CardHeader>
              <CardTitle>{group.title}</CardTitle>
              <CardDescription>{group.description}</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-5 sm:grid-cols-2">
              {groupItems.map((item) => (
                <Field
                  key={item.key}
                  item={item}
                  value={values[item.key] ?? ""}
                  error={fieldErrors[item.key]}
                  disabled={saving}
                  onChange={(raw) => setValue(item.key, raw)}
                />
              ))}
            </CardContent>
          </Card>
        );
      })}

      {/* Status messages */}
      {savedFlash && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-start gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-700 dark:text-emerald-400"
        >
          <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            تم الحفظ. سيطبّق العامل (worker) الإعدادات الجديدة في الدورة التالية.
          </span>
        </div>
      )}
      {generalError && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>{generalError}</span>
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={!dirty || saving}>
          <Save className="size-4" aria-hidden />
          <span>{saving ? "جارٍ الحفظ…" : "حفظ"}</span>
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={handleReset}
          disabled={!dirty || saving}
        >
          <RotateCcw className="size-4" aria-hidden />
          <span>إعادة تعيين</span>
        </Button>
        {dirty && !saving && (
          <span className="text-xs text-muted-foreground">
            تغييرات غير محفوظة (<Bidi>{changedKeys.length}</Bidi>).
          </span>
        )}
      </div>
    </form>
  );
}

function Field({
  item,
  value,
  error,
  disabled,
  onChange,
}: {
  item: SettingItem;
  value: string;
  error?: string;
  disabled: boolean;
  onChange: (raw: string) => void;
}) {
  const id = `setting-${item.key}`;
  const hint = HINTS[item.key];
  const describedBy =
    [error ? `${id}-error` : null, hint ? `${id}-hint` : null]
      .filter(Boolean)
      .join(" ") || undefined;

  // Boolean toggle → Switch instead of a number input.
  if (item.type === "bool") {
    return (
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-3">
          <Label htmlFor={id}>{item.label}</Label>
          <Switch
            id={id}
            checked={value === "true"}
            disabled={disabled}
            aria-describedby={describedBy}
            onCheckedChange={(checked) => onChange(checked ? "true" : "false")}
          />
        </div>
        {hint && (
          <p id={`${id}-hint`} className="text-xs text-muted-foreground">
            {hint}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{item.label}</Label>
      <Input
        id={id}
        type="number"
        inputMode={item.type === "float" ? "decimal" : "numeric"}
        dir="ltr"
        className="text-start tabular-nums"
        step={step(item.type)}
        min={item.min ?? undefined}
        max={item.max ?? undefined}
        value={value}
        disabled={disabled}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        onChange={(e) => onChange(e.target.value)}
      />
      {hint && (
        <p
          id={`${id}-hint`}
          className={cn("text-xs text-muted-foreground", error && "sr-only")}
        >
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-xs font-medium text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
