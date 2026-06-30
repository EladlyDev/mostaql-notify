import type { CompetitionDynamics, CompetitionPoint } from "@/lib/types";
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

/**
 * Competition dynamics (Feature 6): how the median number of bids grows with a
 * project's age, plus the time-of-day at which bidding happens. Pure inline SVG
 * (no charting dep), RTL-aware like {@link BidChart} — the youngest age band
 * sits on the RIGHT, the oldest on the LEFT.
 */

const VIEW_W = 320;
const VIEW_H = 120;
const PAD_X = 10;
const PAD_Y = 12;
const INNER_W = VIEW_W - PAD_X * 2;
const INNER_H = VIEW_H - PAD_Y * 2;

const OPEN_BAND = 9999;
const HOUR_LABELS = new Set([0, 6, 12, 18, 23]);

/** Hours range label for an age band; the open top band reads "+lo س". */
function bandLabel(p: CompetitionPoint): string {
  if (p.age_hi_h >= OPEN_BAND) return `+${formatNumber(p.age_lo_h)}س`;
  return `${formatNumber(p.age_lo_h)}–${formatNumber(p.age_hi_h)}س`;
}

/** Per-point hover text. */
function pointTitle(p: CompetitionPoint): string {
  return `عمر ${formatNumber(p.age_lo_h)}–${formatNumber(
    p.age_hi_h
  )}س: وسيط ${formatNumber(p.median)} عرض (ربع ${formatNumber(
    p.p25
  )}–${formatNumber(p.p75)})`;
}

export function CompetitionChart({ data }: { data: CompetitionDynamics }) {
  if (!data.enough_data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>ديناميكية المنافسة</CardTitle>
          <CardDescription>
            كيف يتزايد عدد العروض مع عمر المشروع
          </CardDescription>
        </CardHeader>
        <CardContent>
          <NotEnoughData testId="competition-empty" />
        </CardContent>
      </Card>
    );
  }

  const curve = data.age_curve;
  const n = curve.length;

  // y scaled by the tallest IQR top, never below the crowded threshold.
  const yMax = Math.max(
    1,
    data.crowded_bids,
    ...curve.map((p) => p.p75)
  );

  // RTL x-axis: index 0 (youngest) → right edge, last (oldest) → left edge.
  const xOf = (i: number) =>
    n <= 1 ? PAD_X + INNER_W / 2 : PAD_X + INNER_W - (i / (n - 1)) * INNER_W;
  const yOf = (v: number) => PAD_Y + INNER_H - (v / yMax) * INNER_H;

  const coords = curve.map((p, i) => ({
    x: xOf(i),
    yMed: yOf(p.median),
    y25: yOf(p.p25),
    y75: yOf(p.p75),
    point: p,
  }));

  const medianLine = coords.map((c) => `${c.x},${c.yMed}`).join(" ");
  // IQR ribbon: along p75 (upper) then back along p25 (lower).
  const iqrBand = [
    ...coords.map((c) => `${c.x},${c.y75}`),
    ...[...coords].reverse().map((c) => `${c.x},${c.y25}`),
  ].join(" ");

  const refY = yOf(data.crowded_bids);

  // Vertical marker at the age band that contains the crowding threshold.
  let crowdedX: number | null = null;
  if (data.crowded_after_hours != null && n > 0) {
    const age = data.crowded_after_hours;
    let idx = curve.findIndex(
      (p) => age >= p.age_lo_h && age < p.age_hi_h
    );
    if (idx === -1) idx = n - 1; // beyond all known bands → clamp to oldest
    crowdedX = xOf(idx);
  }

  const byHourMax = Math.max(1, ...data.by_hour);

  return (
    <Card>
      <CardHeader>
        <CardTitle>ديناميكية المنافسة</CardTitle>
        <CardDescription>كيف يتزايد عدد العروض مع عمر المشروع</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p data-testid="competition-headline" className="text-sm font-medium">
          <Bidi>{data.headline}</Bidi>
        </p>

        {/* Median bids-vs-age curve with IQR ribbon. */}
        <figure className="flex flex-col gap-2">
          <svg
            data-testid="competition-chart"
            viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
            className="h-32 w-full"
            role="img"
            aria-label="منحنى وسيط عدد العروض حسب عمر المشروع"
            preserveAspectRatio="none"
          >
            {n > 1 && (
              <polygon
                points={iqrBand}
                className="fill-primary/15"
                stroke="none"
              />
            )}
            {data.crowded_bids > 0 && (
              <line
                x1={PAD_X}
                y1={refY}
                x2={PAD_X + INNER_W}
                y2={refY}
                stroke="currentColor"
                strokeWidth={1}
                strokeDasharray="4 4"
                className="text-muted-foreground"
              >
                <title>حد الازدحام: {formatNumber(data.crowded_bids)} عرض</title>
              </line>
            )}
            {crowdedX != null && (
              <line
                x1={crowdedX}
                y1={PAD_Y}
                x2={crowdedX}
                y2={PAD_Y + INNER_H}
                stroke="currentColor"
                strokeWidth={1}
                strokeDasharray="4 4"
                className="text-muted-foreground"
              >
                <title>
                  يصبح مزدحمًا بعد {formatNumber(data.crowded_after_hours)} ساعة
                </title>
              </line>
            )}
            {n > 1 && (
              <polyline
                points={medianLine}
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                className="text-primary"
              />
            )}
            {coords.map((c, i) => (
              <circle
                key={i}
                data-testid="competition-point"
                cx={c.x}
                cy={c.yMed}
                r={3}
                className="fill-primary"
              >
                <title>{pointTitle(c.point)}</title>
              </circle>
            ))}
          </svg>

          {/* RTL band axis: youngest on the right, oldest on the left. */}
          <figcaption className="flex justify-between text-xs text-muted-foreground">
            {curve.map((p, i) => (
              <span key={i} className="text-center">
                <Bidi>{bandLabel(p)}</Bidi>
              </span>
            ))}
          </figcaption>
        </figure>

        {/* Bidding by hour of day. RTL: hour 0 on the right, 23 on the left. */}
        <div data-testid="competition-by-hour" className="flex flex-col gap-1">
          <p className="text-xs text-muted-foreground">العروض حسب ساعة اليوم</p>
          <div className="flex h-16 items-end gap-px">
            {data.by_hour.map((v, h) => (
              <div
                key={h}
                className="min-h-px flex-1 rounded-t-sm bg-primary/70"
                style={{ height: `${(v / byHourMax) * 100}%` }}
                title={`الساعة ${formatNumber(h)}: ${formatNumber(v)} عرض`}
              />
            ))}
          </div>
          <div className="flex gap-px">
            {data.by_hour.map((_, h) => (
              <span
                key={h}
                className="flex-1 text-center text-[10px] text-muted-foreground"
              >
                {HOUR_LABELS.has(h) ? <Bidi>{formatNumber(h)}</Bidi> : null}
              </span>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
