/// <reference types="vitest/globals" />
import { render, screen } from "@testing-library/react";

import type { HeatmapCell, PostingHeatmap } from "@/lib/types";
import { Heatmap } from "@/components/analytics/Heatmap";

// ---------------------------------------------------------------------------
// Fixture factory
// ---------------------------------------------------------------------------
const WEEKDAY_LABELS = [
  "السبت",
  "الأحد",
  "الإثنين",
  "الثلاثاء",
  "الأربعاء",
  "الخميس",
  "الجمعة",
];

function cell(over: Partial<HeatmapCell> = {}): HeatmapCell {
  return { weekday: 0, hour: 9, count: 1, ...over };
}

function heatmap(over: Partial<PostingHeatmap> = {}): PostingHeatmap {
  return {
    cells: [
      cell({ weekday: 0, hour: 9, count: 3 }),
      cell({ weekday: 1, hour: 14, count: 8 }),
      cell({ weekday: 2, hour: 20, count: 5 }),
    ],
    weekday_labels: WEEKDAY_LABELS,
    total: 16,
    peak: cell({ weekday: 1, hour: 14, count: 8 }),
    enough_data: true,
    ...over,
  };
}

// ---------------------------------------------------------------------------
// Heatmap
// ---------------------------------------------------------------------------
describe("Heatmap", () => {
  it("renders the card, a full 7×24 grid of cells, and the Arabic title", () => {
    render(<Heatmap data={heatmap()} />);

    expect(screen.getByTestId("heatmap")).toBeInTheDocument();
    expect(screen.getByText("خريطة أوقات النشر")).toBeInTheDocument();
    // The grid always draws one cell per weekday/hour bucket (7 × 24 = 168).
    expect(screen.getAllByTestId("heatmap-cell")).toHaveLength(7 * 24);
  });

  it("rings exactly the peak bucket and names it in the summary line", () => {
    const { container } = render(<Heatmap data={heatmap()} />);

    // Only the peak cell carries the ring marker class.
    const ringed = container.querySelectorAll(
      '[data-testid="heatmap-cell"].ring-primary'
    );
    expect(ringed).toHaveLength(1);

    // The "most active" summary names the peak weekday and reads in Arabic.
    expect(screen.getByText(/الأكثر نشاطًا/)).toBeInTheDocument();
    expect(screen.getAllByText("الأحد").length).toBeGreaterThan(0);
  });

  it("exposes the Arabic weekday labels (RTL row headers)", () => {
    render(<Heatmap data={heatmap()} />);
    for (const label of WEEKDAY_LABELS) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it("shows the empty state (and no cells) when enough_data is false", () => {
    render(<Heatmap data={heatmap({ enough_data: false, peak: null })} />);

    expect(screen.getByTestId("heatmap-empty")).toBeInTheDocument();
    // The grid root (its cells) must not render in the thin-data state.
    expect(screen.queryByTestId("heatmap-cell")).not.toBeInTheDocument();
    expect(screen.queryByText(/الأكثر نشاطًا/)).not.toBeInTheDocument();
  });
});
