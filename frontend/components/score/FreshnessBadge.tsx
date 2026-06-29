import type { JSX } from "react";

import type { Freshness } from "@/lib/types";
import { cn } from "@/lib/utils";

// Colour + Arabic title for each freshness signal. RTL-safe: the dot is a
// neutral round swatch, so no directional layout is needed.
const FRESHNESS_META: Record<Freshness, { label: string; dot: string }> = {
  green: { label: "حديث ومنخفض المنافسة", dot: "bg-emerald-500" },
  yellow: { label: "متوسط الحداثة", dot: "bg-amber-500" },
  red: { label: "قديم أو مرتفع المنافسة", dot: "bg-red-500" },
};

/**
 * A small coloured dot conveying a scored project's freshness
 * (green / yellow / red). Renders nothing when `freshness` is null.
 */
export function FreshnessBadge({
  freshness,
}: {
  freshness: Freshness | null;
}): JSX.Element | null {
  if (!freshness) return null;
  const meta = FRESHNESS_META[freshness];
  return (
    <span
      role="status"
      data-freshness={freshness}
      title={meta.label}
      aria-label={meta.label}
      className="inline-flex shrink-0 items-center"
    >
      <span
        className={cn("inline-block size-2.5 rounded-full", meta.dot)}
        aria-hidden
      />
    </span>
  );
}
