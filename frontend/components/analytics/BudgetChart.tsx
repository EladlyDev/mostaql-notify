import type { BudgetBucket, BudgetDistribution } from "@/lib/types";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { NotEnoughData } from "@/components/analytics/NotEnoughData";
import { Bidi } from "@/components/Bidi";
import { formatNumber, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Budget distribution (Feature 6 analytics, FR budget mix): a histogram of
 * project budget bands plus a tier-one / tier-two / unknown share split. Pure
 * render — no client hooks — and RTL / bidi-safe throughout.
 */

/** Bidi-safe label for a budget band. The unknown band (lo=hi=null) reads
 *  "غير معروفة"; an open-top band (hi=null) reads "+lo$"; otherwise "lo–hi$". */
function bucketLabel(bucket: BudgetBucket): string {
  const { lo, hi } = bucket;
  if (lo === null && hi === null) return "غير معروفة";
  if (lo !== null && hi === null) return `+${formatNumber(lo)}$`;
  return `${formatNumber(lo)}–${formatNumber(hi)}$`;
}

export function BudgetChart({ data }: { data: BudgetDistribution }) {
  const tiers: { label: string; count: number; bar: string }[] = [
    { label: "الفئة الأولى", count: data.tier1_count, bar: "bg-primary" },
    { label: "الفئة الثانية", count: data.tier2_count, bar: "bg-primary/50" },
    { label: "غير محددة", count: data.unknown_count, bar: "bg-muted" },
  ];

  const total = data.total;
  const maxCount = Math.max(1, ...data.buckets.map((b) => b.count));

  return (
    <Card>
      <CardHeader>
        <CardTitle>توزيع الميزانيات</CardTitle>
        <CardDescription>
          نطاقات الميزانية وحصة الفئة الأولى مقابل الثانية
        </CardDescription>
      </CardHeader>

      {!data.enough_data ? (
        <CardContent>
          <NotEnoughData testId="budget-empty" />
        </CardContent>
      ) : (
        <CardContent data-testid="budget-chart" className="flex flex-col gap-6">
          {/* Histogram of budget bands. */}
          <div
            data-testid="budget-histogram"
            className="flex items-end gap-2 overflow-x-auto"
          >
            {data.buckets.map((bucket, i) => {
              const isUnknown = bucket.lo === null && bucket.hi === null;
              const heightPct = (bucket.count / maxCount) * 100;
              return (
                <div
                  key={i}
                  data-testid="budget-bar"
                  className="flex min-w-12 flex-1 flex-col items-center gap-1"
                >
                  <Bidi className="text-xs text-muted-foreground">
                    {formatNumber(bucket.count)}
                  </Bidi>
                  <div className="flex h-32 w-full items-end">
                    <div
                      className={cn(
                        "w-full rounded-t",
                        isUnknown ? "bg-muted-foreground/40" : "bg-primary"
                      )}
                      style={{ height: `${heightPct}%` }}
                    />
                  </div>
                  <Bidi className="text-center text-[11px] leading-tight text-muted-foreground">
                    {bucketLabel(bucket)}
                  </Bidi>
                </div>
              );
            })}
          </div>

          {/* Tier-one / tier-two / unknown share split. */}
          <div data-testid="budget-tiers" className="flex flex-col gap-3">
            <div className="flex h-4 w-full overflow-hidden rounded-full bg-muted">
              {total > 0 &&
                tiers.map((tier, i) => (
                  <div
                    key={i}
                    className={tier.bar}
                    style={{ width: `${(tier.count / total) * 100}%` }}
                  />
                ))}
            </div>
            <ul className="flex flex-wrap gap-x-6 gap-y-2 text-xs">
              {tiers.map((tier, i) => (
                <li key={i} className="flex items-center gap-2">
                  <span
                    aria-hidden
                    className={cn("size-3 shrink-0 rounded-sm", tier.bar)}
                  />
                  <span className="text-muted-foreground">{tier.label}</span>
                  <Bidi className="font-medium">{formatNumber(tier.count)}</Bidi>
                  <Bidi className="text-muted-foreground">
                    {formatPercent(total > 0 ? tier.count / total : null)}
                  </Bidi>
                </li>
              ))}
            </ul>
          </div>
        </CardContent>
      )}
    </Card>
  );
}
