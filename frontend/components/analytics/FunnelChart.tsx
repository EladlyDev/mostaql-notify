import type { Funnel, FunnelStage } from "@/lib/types";
import { formatNumber, formatPercent } from "@/lib/format";
import { Bidi } from "@/components/Bidi";
import { NotEnoughData } from "@/components/analytics/NotEnoughData";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/**
 * Feature 6 — conversion funnel from "seen" to "won". A dependency-free CSS
 * funnel: each stage is a horizontal bar whose width is its share of `seen`,
 * anchored to the right edge (global RTL) so the bars taper leftward and the
 * "leak" between stages reads at a glance. Every numeric is bidi-isolated.
 */

/** Share of the widest stage (`seen`) as a 0–100 percentage, clamped and
 *  guarded against a zero denominator. */
function barWidth(stage: FunnelStage, seen: number): number {
  if (seen <= 0) return 0;
  return Math.min(100, Math.max(0, (stage.count / seen) * 100));
}

export function FunnelChart({ data }: { data: Funnel }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>مسار التحويل</CardTitle>
        <CardDescription>
          من الظهور إلى الفوز — أين يحدث التسرّب
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!data.enough_data ? (
          <NotEnoughData testId="funnel-empty" />
        ) : (
          <div data-testid="funnel-chart" className="flex flex-col gap-5">
            {data.stages.map((stage) => {
              const width = barWidth(stage, data.seen);
              const conv =
                stage.conv_from_prev === null
                  ? "—"
                  : formatPercent(stage.conv_from_prev);
              const lag =
                stage.lag_median_hours === null
                  ? "غير متاح"
                  : `${formatNumber(stage.lag_median_hours)} ساعة`;

              return (
                <div
                  key={stage.key}
                  data-testid="funnel-stage"
                  className="flex flex-col gap-1.5"
                >
                  <div className="flex items-baseline justify-between gap-2 text-sm">
                    <span className="font-medium">{stage.label}</span>
                    <Bidi className="tabular-nums text-muted-foreground">
                      {formatNumber(stage.count)}
                    </Bidi>
                  </div>

                  {/* RTL track: the bar is pinned to the physical right edge and
                      grows leftward, so successive stages narrow toward the left. */}
                  <div className="relative h-6 w-full overflow-hidden rounded-md bg-muted">
                    <div
                      className="absolute inset-y-0 right-0 rounded-md bg-primary"
                      style={{ width: `${width}%` }}
                    />
                  </div>

                  <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span>
                      تحويل من السابق:{" "}
                      <Bidi className="font-medium text-foreground">{conv}</Bidi>
                    </span>
                    <span>
                      متوسط المهلة:{" "}
                      <Bidi className="font-medium text-foreground">{lag}</Bidi>
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
