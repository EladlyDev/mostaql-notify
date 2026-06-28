"use client";

import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";

// Terminal pipeline stages that reveal an outcome field.
export const STATUS_WON = "won";
export const STATUS_LOST = "lost";

export interface OutcomePatch {
  won_amount?: number | null;
  lost_reason?: string | null;
}

/** Parse a number input into a non-negative value, or null when cleared. */
function parseAmount(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n < 0) return null;
  return n;
}

/**
 * Contextual outcome capture: a non-negative amount when the project is "won",
 * a free-text reason when it is "lost". Renders nothing for any other stage.
 */
export function OutcomeFields({
  status,
  wonAmount,
  lostReason,
  onChange,
  idPrefix = "outcome",
}: {
  status: string;
  wonAmount: number | null;
  lostReason: string | null;
  onChange: (patch: OutcomePatch) => void;
  idPrefix?: string;
}) {
  if (status === STATUS_WON) {
    const id = `${idPrefix}-won-amount`;
    return (
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={id}>قيمة الصفقة</Label>
        <Input
          id={id}
          type="number"
          inputMode="decimal"
          min={0}
          step="0.01"
          dir="ltr"
          className="text-start tabular-nums"
          value={wonAmount ?? ""}
          placeholder="0"
          onChange={(e) => onChange({ won_amount: parseAmount(e.target.value) })}
        />
      </div>
    );
  }

  if (status === STATUS_LOST) {
    const id = `${idPrefix}-lost-reason`;
    return (
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={id}>سبب الخسارة</Label>
        <textarea
          id={id}
          rows={3}
          value={lostReason ?? ""}
          placeholder="ما سبب عدم الفوز بالمشروع؟"
          onChange={(e) =>
            onChange({ lost_reason: e.target.value === "" ? null : e.target.value })
          }
          className="w-full min-w-0 resize-y rounded-lg border border-input bg-transparent px-2.5 py-1.5 text-sm transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 dark:bg-input/30"
        />
      </div>
    );
  }

  return null;
}
