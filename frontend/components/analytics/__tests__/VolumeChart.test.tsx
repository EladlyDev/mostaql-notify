/// <reference types="vitest/globals" />
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { VolumePoint, VolumeTrends } from "@/lib/types";
import { VolumeChart } from "@/components/analytics/VolumeChart";

// ---------------------------------------------------------------------------
// Fixture factory
// ---------------------------------------------------------------------------
function point(over: Partial<VolumePoint> = {}): VolumePoint {
  return { period: "2026-06-25", total: 10, qualified: 4, ...over };
}

function volume(over: Partial<VolumeTrends> = {}): VolumeTrends {
  return {
    by_day: [
      point({ period: "2026-06-25", total: 10, qualified: 4 }),
      point({ period: "2026-06-26", total: 14, qualified: 6 }),
      point({ period: "2026-06-27", total: 9, qualified: 3 }),
    ],
    by_week: [
      point({ period: "2026-W24", total: 40, qualified: 18 }),
      point({ period: "2026-W25", total: 52, qualified: 23 }),
    ],
    category: "all",
    enough_data: true,
    ...over,
  };
}

// ---------------------------------------------------------------------------
// VolumeChart
// ---------------------------------------------------------------------------
describe("VolumeChart", () => {
  it("renders the daily chart by default with two points per bucket", () => {
    render(<VolumeChart data={volume()} />);

    expect(screen.getByText("حجم المشاريع")).toBeInTheDocument();
    const chart = screen.getByTestId("volume-chart");
    expect(chart).toBeInTheDocument();
    expect(chart.getAttribute("role")).toBe("img");

    // Default tab is daily — the aria-label spans the day count.
    const label = chart.getAttribute("aria-label") ?? "";
    expect(label).toContain("مخطط حجم المشاريع");
    expect(label).toContain("يوم");

    // One total + one qualified dot per day bucket (3 days → 6 points).
    expect(screen.getAllByTestId("volume-point")).toHaveLength(6);

    // RTL legend: total vs. qualified series.
    expect(screen.getByText("إجمالي")).toBeInTheDocument();
    expect(screen.getByText("مؤهل")).toBeInTheDocument();
  });

  it("toggles to the weekly series, making by_week data reachable", async () => {
    render(<VolumeChart data={volume()} />);

    // Both toggles present.
    expect(screen.getByText("يومي")).toBeInTheDocument();
    const weekly = screen.getByText("أسبوعي");

    fireEvent.click(weekly);

    // The weekly panel mounts: its aria-label now reads in weeks, and there
    // are 2 weeks × 2 series = 4 points.
    await waitFor(() => {
      const chart = screen.getByTestId("volume-chart");
      expect(chart.getAttribute("aria-label") ?? "").toContain("أسبوع");
    });
    expect(screen.getAllByTestId("volume-point")).toHaveLength(4);
  });

  it("shows the empty state (and no chart) when enough_data is false", () => {
    render(<VolumeChart data={volume({ enough_data: false })} />);

    expect(screen.getByTestId("volume-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("volume-chart")).not.toBeInTheDocument();
  });
});
