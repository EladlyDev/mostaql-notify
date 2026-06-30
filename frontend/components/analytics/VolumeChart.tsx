"use client";

import { useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { NotEnoughData } from "@/components/analytics/NotEnoughData";
import { formatDateOnly, formatNumber } from "@/lib/format";
import type { VolumePoint, VolumeTrends } from "@/lib/types";

/**
 * Dependency-free inline-SVG of project volume over time (FR analytics):
 * two polylines per period series — `total` (muted) and `qualified` (primary).
 * RTL-aware like {@link BidChart}: periods flow right→left, so the oldest
 * bucket sits on the right edge and the newest on the left. A daily/weekly
 * toggle swaps the active series. Degrades gracefully — an empty series shows
 * a note, a single bucket shows lone dots with no connecting line.
 */

const VIEW_W = 320;
const VIEW_H = 112;
const PAD_X = 10;
const PAD_Y = 10;

function VolumeSeriesChart({
  points,
  weekly,
}: {
  points: VolumePoint[];
  weekly: boolean;
}) {
  if (points.length === 0) {
    return (
      <NotEnoughData message="لا توجد بيانات في هذه الفترة بعد" className="py-6" />
    );
  }

  const innerW = VIEW_W - PAD_X * 2;
  const innerH = VIEW_H - PAD_Y * 2;

  const n = points.length;
  const single = n === 1;

  // Scale the y-axis by the tallest `total`; `qualified` is always ≤ `total`.
  const yMax = Math.max(1, ...points.map((p) => p.total));

  // RTL x-axis: oldest period (index 0) → right edge, newest → left edge.
  const xOf = (i: number) =>
    single ? PAD_X + innerW / 2 : PAD_X + innerW - (i / (n - 1)) * innerW;
  const yOf = (v: number) => PAD_Y + innerH - (v / yMax) * innerH;

  const coords = points.map((p, i) => {
    const label = weekly ? p.period : formatDateOnly(p.period);
    return {
      x: xOf(i),
      yTotal: yOf(p.total),
      yQualified: yOf(p.qualified),
      title: `${label}: ${formatNumber(p.total)} إجمالي، ${formatNumber(
        p.qualified
      )} مؤهل`,
    };
  });

  const totalLine = coords.map((c) => `${c.x},${c.yTotal}`).join(" ");
  const qualifiedLine = coords.map((c) => `${c.x},${c.yQualified}`).join(" ");

  return (
    <figure className="flex flex-col gap-3">
      <svg
        data-testid="volume-chart"
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="h-28 w-full"
        role="img"
        aria-label={`مخطط حجم المشاريع لعدد ${formatNumber(n)} ${
          weekly ? "أسبوع" : "يوم"
        }: الإجمالي والمؤهل`}
        preserveAspectRatio="none"
      >
        {!single && (
          <polyline
            points={totalLine}
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-muted-foreground"
          />
        )}
        {!single && (
          <polyline
            points={qualifiedLine}
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-primary"
          />
        )}
        {coords.map((c, i) => (
          <g key={i}>
            <circle
              data-testid="volume-point"
              cx={c.x}
              cy={c.yTotal}
              r={single ? 4 : 3}
              className="fill-muted-foreground"
            >
              <title>{c.title}</title>
            </circle>
            <circle
              data-testid="volume-point"
              cx={c.x}
              cy={c.yQualified}
              r={single ? 4 : 3}
              className="fill-primary"
            >
              <title>{c.title}</title>
            </circle>
          </g>
        ))}
      </svg>

      {/* Series legend — total (muted) vs. qualified (primary). */}
      <figcaption className="flex items-center justify-end gap-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className="inline-block h-0.5 w-4 rounded-full bg-muted-foreground"
          />
          إجمالي
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className="inline-block h-0.5 w-4 rounded-full bg-primary"
          />
          مؤهل
        </span>
      </figcaption>
    </figure>
  );
}

export function VolumeChart({ data }: { data: VolumeTrends }) {
  const [tab, setTab] = useState<string>("day");

  return (
    <Card>
      <CardHeader>
        <CardTitle>حجم المشاريع</CardTitle>
        <CardDescription>إجمالي المشاريع والمؤهلة عبر الزمن</CardDescription>
      </CardHeader>
      <CardContent>
        {!data.enough_data ? (
          <NotEnoughData testId="volume-empty" />
        ) : (
          <Tabs
            value={tab}
            onValueChange={(next) => setTab(String(next))}
            className="gap-3"
          >
            <TabsList>
              <TabsTrigger value="day">يومي</TabsTrigger>
              <TabsTrigger value="week">أسبوعي</TabsTrigger>
            </TabsList>

            <TabsContent value="day">
              <VolumeSeriesChart points={data.by_day} weekly={false} />
            </TabsContent>

            <TabsContent value="week">
              <VolumeSeriesChart points={data.by_week} weekly={true} />
            </TabsContent>
          </Tabs>
        )}
      </CardContent>
    </Card>
  );
}
