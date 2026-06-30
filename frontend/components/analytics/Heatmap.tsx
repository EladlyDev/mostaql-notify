import { Fragment } from "react";

import type { PostingHeatmap } from "@/lib/types";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { NotEnoughData } from "@/components/analytics/NotEnoughData";
import { Bidi } from "@/components/Bidi";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Dependency-free posting-time heatmap (Feature 6 analytics). A 7×24 grid —
 * one row per weekday (index 0 = Saturday, RTL-friendly Arabic labels) and one
 * column per hour-of-day — where each cell's `bg-primary` opacity scales with
 * how many qualified projects appeared in that day/hour bucket. The busiest
 * bucket (`data.peak`) is ringed. The grid scrolls horizontally on narrow
 * screens, and is honest about thin data via `<NotEnoughData>`.
 */

const HOURS = Array.from({ length: 24 }, (_, h) => h);
const WEEKDAYS = Array.from({ length: 7 }, (_, d) => d);

// Hour markers shown on the axis — enough to orient without crowding.
const AXIS_HOURS = new Set([0, 6, 12, 18, 23]);

function cellKey(weekday: number, hour: number): string {
  return `${weekday}-${hour}`;
}

export function Heatmap({ data }: { data: PostingHeatmap }) {
  return (
    <Card data-testid="heatmap">
      <CardHeader>
        <CardTitle>خريطة أوقات النشر</CardTitle>
        <CardDescription>
          متى تظهر المشاريع المؤهلة — حسب اليوم والساعة (بتوقيت التحليلات)
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!data.enough_data ? (
          <NotEnoughData testId="heatmap-empty" />
        ) : (
          <HeatmapGrid data={data} />
        )}
      </CardContent>
    </Card>
  );
}

function HeatmapGrid({ data }: { data: PostingHeatmap }) {
  const counts = new Map<string, number>();
  for (const cell of data.cells) {
    counts.set(cellKey(cell.weekday, cell.hour), cell.count);
  }

  const max = Math.max(1, ...data.cells.map((cell) => cell.count));
  const labels = data.weekday_labels;
  const peak = data.peak;

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto">
        <div
          className="grid w-fit min-w-full gap-0.5"
          style={{
            gridTemplateColumns: `auto repeat(24, minmax(0.9rem, 1fr))`,
          }}
        >
          {/* Hour axis: leading corner is the empty space above the day labels. */}
          <div aria-hidden className="px-1" />
          {HOURS.map((hour) => (
            <div
              key={`axis-${hour}`}
              aria-hidden
              className="text-center text-[10px] leading-none text-muted-foreground"
            >
              {AXIS_HOURS.has(hour) ? <Bidi>{formatNumber(hour)}</Bidi> : null}
            </div>
          ))}

          {/* One row per weekday. */}
          {WEEKDAYS.map((weekday) => (
            <Fragment key={`row-${weekday}`}>
              <div className="self-center whitespace-nowrap pe-2 text-xs text-muted-foreground">
                {labels[weekday]}
              </div>
              {HOURS.map((hour) => {
                const count = counts.get(cellKey(weekday, hour)) ?? 0;
                const opacity = count > 0 ? 0.12 + 0.88 * (count / max) : 0;
                const isPeak =
                  peak != null &&
                  peak.weekday === weekday &&
                  peak.hour === hour;
                return (
                  <div
                    key={`cell-${weekday}-${hour}`}
                    data-testid="heatmap-cell"
                    title={`${labels[weekday]} الساعة ${hour} — ${count} مشروع`}
                    className={cn(
                      "aspect-square rounded-sm",
                      count > 0 ? "bg-primary" : "bg-muted",
                      isPeak && "ring-2 ring-primary"
                    )}
                    style={count > 0 ? { opacity } : undefined}
                  />
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>

      {peak ? (
        <p className="text-xs text-muted-foreground">
          الأكثر نشاطًا:{" "}
          <span className="text-foreground">{labels[peak.weekday]}</span> الساعة{" "}
          <Bidi className="text-foreground">{formatNumber(peak.hour)}</Bidi> (
          <Bidi>{formatNumber(peak.count)}</Bidi> مشروع)
        </p>
      ) : null}
    </div>
  );
}
