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
    mutationFn: (patch: Record<string, number>) => updateSettings(patch),
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

    const patch: Record<string, number> = {};
    for (const key of changedKeys) patch[key] = Number(values[key].trim());
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
