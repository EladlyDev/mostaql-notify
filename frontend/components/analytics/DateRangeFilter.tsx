"use client";

import { RotateCw } from "lucide-react";

import {
  RANGE_PRESETS,
  type RangePreset,
  type UseAnalyticsResult,
} from "@/lib/useAnalytics";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Analytics date-range control: quick presets + custom من/إلى bounds + refresh.
// Drives the URL-backed `useAnalytics` controller (calendar dates, analytics tz).
// ---------------------------------------------------------------------------

const PRESET_LABELS: Record<RangePreset, string> = {
  7: "آخر ٧ أيام",
  30: "آخر ٣٠ يومًا",
  90: "آخر ٩٠ يومًا",
};

/**
 * Calendar date `n` days ago as `YYYY-MM-DD`, anchored at local midnight.
 * The offset shift makes `toISOString()` yield the *local* calendar date
 * (not a UTC-shifted neighbour) so presets line up with the analytics tz.
 */
function daysAgoIso(n: number): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0); // local midnight today
  d.setDate(d.getDate() - n); // n days back
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

export function DateRangeFilter({
  controller,
}: {
  controller: UseAnalyticsResult;
}) {
  const { params, setRange, refetch, isFetching } = controller;

  const today = daysAgoIso(0);
  // Which preset (if any) exactly matches the current bounds — drives ToggleGroup state.
  const activePreset = RANGE_PRESETS.find(
    (n) => params.date_from === daysAgoIso(n) && params.date_to === today
  );
  const presetValue = activePreset !== undefined ? [String(activePreset)] : [];

  const setBound = (bound: "date_from" | "date_to", value: string) =>
    setRange({ ...params, [bound]: value || undefined });

  return (
    <section
      data-testid="date-range-filter"
      aria-label="الفترة الزمنية"
      className="flex flex-wrap items-end gap-3 rounded-lg border bg-card p-4"
    >
      {/* Quick presets */}
      <div className="flex flex-col gap-1.5">
        <Label>فترة سريعة</Label>
        <ToggleGroup
          value={presetValue}
          onValueChange={(groupValue) => {
            const raw = groupValue[groupValue.length - 1];
            if (!raw) return; // toggled off — keep the current range
            const n = Number(raw);
            setRange({ date_from: daysAgoIso(n), date_to: today });
          }}
          variant="outline"
          aria-label="فترة سريعة"
        >
          {RANGE_PRESETS.map((n) => (
            <ToggleGroupItem key={n} value={String(n)} aria-label={PRESET_LABELS[n]}>
              {PRESET_LABELS[n]}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>

      {/* Custom bounds */}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="date_from">من</Label>
        <Input
          id="date_from"
          type="date"
          dir="ltr"
          className="w-auto"
          value={params.date_from ?? ""}
          onChange={(e) => setBound("date_from", e.target.value)}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="date_to">إلى</Label>
        <Input
          id="date_to"
          type="date"
          dir="ltr"
          className="w-auto"
          value={params.date_to ?? ""}
          onChange={(e) => setBound("date_to", e.target.value)}
        />
      </div>

      {/* Refresh */}
      <Button
        variant="outline"
        size="sm"
        onClick={() => refetch()}
        disabled={isFetching}
        aria-label="تحديث"
      >
        <RotateCw
          className={cn("size-4", isFetching && "animate-spin")}
          aria-hidden
        />
        <span>تحديث</span>
      </Button>
    </section>
  );
}
