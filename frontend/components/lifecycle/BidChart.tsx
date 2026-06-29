import type { Snapshot } from "@/lib/types";
import { Bidi } from "@/components/Bidi";
import { formatAbsolute } from "@/lib/format";

/**
 * Dependency-free inline-SVG sparkline of `bids_count` over `captured_at`
 * (FR-022 bid trajectory). RTL-aware: time flows right→left, so the oldest
 * snapshot sits on the right edge and the newest on the left. Degrades
 * gracefully — an empty trajectory shows a note, a single observation shows a
 * lone dot.
 */

const VIEW_W = 320;
const VIEW_H = 96;
const PAD_X = 10;
const PAD_Y = 10;

const numFmt = new Intl.NumberFormat("ar-EG");

function bidsOf(s: Snapshot): number {
  return s.bids_count ?? 0;
}

export function BidChart({ snapshots }: { snapshots: Snapshot[] }) {
  const points = snapshots ?? [];

  if (points.length === 0) {
    return (
      <p
        data-testid="bid-chart-empty"
        className="text-sm text-muted-foreground"
      >
        لا يوجد سجل عروض بعد.
      </p>
    );
  }

  const innerW = VIEW_W - PAD_X * 2;
  const innerH = VIEW_H - PAD_Y * 2;

  const times = points.map((p) => new Date(p.captured_at).getTime());
  const tMin = Math.min(...times);
  const tMax = Math.max(...times);
  const tSpan = tMax - tMin || 1;

  const bidsMax = Math.max(1, ...points.map(bidsOf));

  // RTL x-axis: oldest (tMin) → right edge, newest (tMax) → left edge.
  const xOf = (t: number) =>
    PAD_X + innerW - ((t - tMin) / tSpan) * innerW;
  const yOf = (bids: number) =>
    PAD_Y + innerH - (bids / bidsMax) * innerH;

  const coords = points.map((p, i) => ({
    x: xOf(times[i]),
    y: yOf(bidsOf(p)),
    bids: bidsOf(p),
    at: p.captured_at,
  }));

  const single = coords.length === 1;
  const polyline = coords.map((c) => `${c.x},${c.y}`).join(" ");

  const latest = points[points.length - 1];
  const earliest = points[0];

  return (
    <figure className="flex flex-col gap-2">
      <svg
        data-testid="bid-chart"
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        className="h-24 w-full"
        role="img"
        aria-label={`مسار العروض: من ${numFmt.format(
          bidsOf(earliest)
        )} إلى ${numFmt.format(bidsOf(latest))} عرضًا`}
        preserveAspectRatio="none"
      >
        {!single && (
          <polyline
            points={polyline}
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
            data-testid="bid-point"
            cx={c.x}
            cy={c.y}
            r={single ? 4 : 3}
            className="fill-primary"
          >
            <title>
              {numFmt.format(c.bids)} عرضًا — {formatAbsolute(c.at)}
            </title>
          </circle>
        ))}
      </svg>

      {/* RTL axis: newest on the left, oldest on the right. */}
      <figcaption className="flex justify-between text-xs text-muted-foreground">
        <span>
          <Bidi>{formatAbsolute(latest.captured_at)}</Bidi>
        </span>
        <span>
          <Bidi>{formatAbsolute(earliest.captured_at)}</Bidi>
        </span>
      </figcaption>
    </figure>
  );
}
