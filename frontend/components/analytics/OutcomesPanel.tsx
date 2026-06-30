import type {
  OutcomeAnalytics,
  MissedProject,
  TimeToClose,
} from "@/lib/types";
import { formatNumber, formatPercent, formatBudget } from "@/lib/format";
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
 * Feature 6 — what became of the qualified projects we watched: the hired vs
 * no-hire split, how long they took to close, and the opportunities we let
 * slip past. Pure render (server-renderable). Part A (shares + time-to-close)
 * is gated on `enough_data`; Part B (missed) is always honest, even at zero.
 */

/** A 0–1 fraction → a CSS width string, never coercing a missing share to a
 *  misleading sliver. Null collapses the segment to 0 width. */
function widthOf(fraction: number | null): string {
  const pct = fraction === null || Number.isNaN(fraction) ? 0 : fraction * 100;
  return `${pct}%`;
}

/** Hours stat, bidi-safe. Null → "غير متاح" (distinct from a real zero). */
function Hours({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm font-medium">
        {value === null || Number.isNaN(value) ? (
          <span className="text-muted-foreground">غير متاح</span>
        ) : (
          <>
            <Bidi>{formatNumber(value)}</Bidi> ساعة
          </>
        )}
      </dd>
    </div>
  );
}

/** Mean + median time-to-close side by side (median flagged as more robust). */
function TimeToCloseStats({ stats }: { stats: TimeToClose }) {
  return (
    <dl className="flex flex-wrap gap-x-8 gap-y-2">
      <Hours label="الوسطي" value={stats.mean} />
      <Hours label="الوسيط (أكثر متانة)" value={stats.median} />
    </dl>
  );
}

/** A single missed opportunity: linked title + its budget (or "غير محدد"). */
function MissedRow({ project }: { project: MissedProject }) {
  return (
    <li className="flex items-center justify-between gap-3 py-2">
      <a
        href={project.url ?? undefined}
        target="_blank"
        rel="noreferrer"
        className="truncate text-sm font-medium text-primary hover:underline"
      >
        {project.title ?? "—"}
      </a>
      <span className="shrink-0 text-xs text-muted-foreground">
        <Bidi>{formatBudget(project.budget_usd, project.budget_usd, "USD")}</Bidi>
      </span>
    </li>
  );
}

export function OutcomesPanel({ data }: { data: OutcomeAnalytics }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>نتائج المشاريع</CardTitle>
        <CardDescription>
          ما الذي آلت إليه المشاريع المؤهلة المُتابَعة
        </CardDescription>
      </CardHeader>
      <CardContent
        data-testid="outcomes-panel"
        className="flex flex-col gap-6"
      >
        {/* Part A — hired vs no-hire shares + time-to-close. */}
        {!data.enough_data ? (
          <NotEnoughData testId="outcomes-empty" />
        ) : (
          <section className="flex flex-col gap-4">
            <div
              className="flex h-3 w-full overflow-hidden rounded-full bg-muted"
              role="img"
              aria-label="نسبة المشاريع التي تم التوظيف فيها مقابل التي أُغلقت دون توظيف"
            >
              <div
                className="bg-primary"
                style={{ width: widthOf(data.hired_share) }}
              />
              <div
                className="bg-muted-foreground/40"
                style={{ width: widthOf(data.no_hire_share) }}
              />
            </div>

            <dl className="flex flex-wrap gap-x-8 gap-y-2">
              <div className="flex flex-col gap-0.5">
                <dt className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="size-2 rounded-full bg-primary" />
                  تم التوظيف
                </dt>
                <dd className="text-sm font-medium">
                  <Bidi>{formatPercent(data.hired_share)}</Bidi>{" "}
                  <span className="text-xs font-normal text-muted-foreground">
                    (<Bidi>{formatNumber(data.hired_count)}</Bidi>)
                  </span>
                </dd>
              </div>
              <div className="flex flex-col gap-0.5">
                <dt className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="size-2 rounded-full bg-muted-foreground/40" />
                  أُغلق دون توظيف
                </dt>
                <dd className="text-sm font-medium">
                  <Bidi>{formatPercent(data.no_hire_share)}</Bidi>{" "}
                  <span className="text-xs font-normal text-muted-foreground">
                    (<Bidi>{formatNumber(data.no_hire_count)}</Bidi>)
                  </span>
                </dd>
              </div>
            </dl>

            <div className="flex flex-wrap gap-2">
              <span className="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">
                غير محدد <Bidi>{formatNumber(data.unknown_count)}</Bidi>
              </span>
              <span className="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">
                ما زالت مفتوحة <Bidi>{formatNumber(data.open_count)}</Bidi>
              </span>
            </div>

            <TimeToCloseStats stats={data.time_to_close_hours} />
          </section>
        )}

        {/* Part B — missed opportunities (always rendered, even at zero). */}
        <section className="flex flex-col gap-3 border-t pt-4">
          <h3 className="flex items-center gap-2 text-sm font-medium">
            فرص فائتة
            <span className="text-muted-foreground">
              <Bidi>{formatNumber(data.missed_count)}</Bidi>
            </span>
          </h3>

          {data.missed_count > 0 ? (
            <ul data-testid="missed-list" className="divide-y divide-border">
              {data.missed.map((project) => (
                <MissedRow key={project.id} project={project} />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              لا توجد فرص فائتة — أحسنت
            </p>
          )}
        </section>
      </CardContent>
    </Card>
  );
}
