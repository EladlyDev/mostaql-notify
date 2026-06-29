import type { ScoreBreakdown } from "@/lib/types";
import { Bidi } from "@/components/Bidi";
import { cn } from "@/lib/utils";

/**
 * Explainable per-component score breakdown (scoring-model §4 / FR-004, FR-007).
 *
 * One horizontal bar per component, in model order. Each bar's width is its
 * `contribution` measured against the same 0–100 point scale, so the bars are
 * directly comparable and visibly sum to the total `score` (SC-002). Beside each
 * bar we show the Arabic `label`, the contribution in points, and the active
 * (normalized) `weight`. RTL, Tailwind only — no charting dependency.
 */

const ptsFmt = new Intl.NumberFormat("ar-EG", { maximumFractionDigits: 1 });
const pctFmt = new Intl.NumberFormat("ar-EG", {
  style: "percent",
  maximumFractionDigits: 0,
});

// A distinct hue per component so a glance maps colour → factor.
const BAR_COLOR: Record<string, string> = {
  hiring_rate: "bg-emerald-500",
  hire_volume: "bg-teal-500",
  budget: "bg-sky-500",
  competition: "bg-amber-500",
  freshness: "bg-violet-500",
  rating: "bg-rose-500",
};

function clampPct(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

export function ScoreBars({ breakdown }: { breakdown: ScoreBreakdown }) {
  const components = breakdown.components ?? [];

  if (components.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">لا يوجد تفصيل للنقاط.</p>
    );
  }

  return (
    <ul dir="rtl" className="flex flex-col gap-3">
      {components.map((c) => {
        const width = clampPct(c.contribution);
        return (
          <li
            key={c.key}
            data-testid="score-bar"
            className="flex flex-col gap-1"
          >
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="font-medium">{c.label}</span>
              <span className="flex items-baseline gap-2 text-xs text-muted-foreground">
                <span className="font-medium text-foreground">
                  <Bidi>{ptsFmt.format(c.contribution)}</Bidi> نقطة
                </span>
                <span>
                  الوزن <Bidi>{pctFmt.format(c.weight)}</Bidi>
                </span>
              </span>
            </div>
            <div
              className="h-2 w-full overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-label={c.label}
              aria-valuenow={Math.round(width)}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className={cn(
                  "h-full rounded-full",
                  BAR_COLOR[c.key] ?? "bg-primary"
                )}
                style={{ width: `${width}%` }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
