/// <reference types="vitest/globals" />
import { render, screen } from "@testing-library/react";

import type { CompetitionDynamics, CompetitionPoint } from "@/lib/types";
import { CompetitionChart } from "@/components/analytics/CompetitionChart";

// ---------------------------------------------------------------------------
// Fixture factory
// ---------------------------------------------------------------------------
function band(over: Partial<CompetitionPoint> = {}): CompetitionPoint {
  return { age_lo_h: 0, age_hi_h: 6, median: 2, p25: 1, p75: 4, n: 10, ...over };
}

function competition(
  over: Partial<CompetitionDynamics> = {}
): CompetitionDynamics {
  return {
    age_curve: [
      band({ age_lo_h: 0, age_hi_h: 6, median: 2, p25: 1, p75: 4, n: 10 }),
      band({ age_lo_h: 6, age_hi_h: 24, median: 8, p25: 5, p75: 12, n: 14 }),
      band({ age_lo_h: 24, age_hi_h: 9999, median: 15, p25: 10, p75: 22, n: 8 }),
    ],
    crowded_bids: 10,
    crowded_after_hours: 18,
    headline: "تصبح المشاريع مزدحمة بعد ١٨ ساعة تقريبًا",
    by_hour: Array.from({ length: 24 }, (_, h) => h % 5),
    enough_data: true,
    ...over,
  };
}

// ---------------------------------------------------------------------------
// CompetitionChart
// ---------------------------------------------------------------------------
describe("CompetitionChart", () => {
  it("renders the headline, the curve chart, a point per band and the by-hour panel", () => {
    render(<CompetitionChart data={competition()} />);

    expect(screen.getByText("ديناميكية المنافسة")).toBeInTheDocument();

    const headline = screen.getByTestId("competition-headline");
    expect(headline.textContent).toContain(
      "تصبح المشاريع مزدحمة بعد ١٨ ساعة تقريبًا"
    );

    const chart = screen.getByTestId("competition-chart");
    expect(chart).toBeInTheDocument();
    expect(chart.getAttribute("role")).toBe("img");
    expect(chart.getAttribute("aria-label")).toContain(
      "منحنى وسيط عدد العروض"
    );

    // One median point per age band.
    expect(screen.getAllByTestId("competition-point")).toHaveLength(3);

    // The bidding-by-hour panel renders with its Arabic heading.
    expect(screen.getByTestId("competition-by-hour")).toBeInTheDocument();
    expect(screen.getByText("العروض حسب ساعة اليوم")).toBeInTheDocument();
  });

  it("draws one bar per hour of day (24)", () => {
    render(<CompetitionChart data={competition()} />);
    const byHour = screen.getByTestId("competition-by-hour");
    // Each hour bar carries a `title="الساعة …"` tooltip.
    const bars = byHour.querySelectorAll('div[title^="الساعة"]');
    expect(bars).toHaveLength(24);
  });

  it("shows the empty state (and no chart) when enough_data is false", () => {
    render(<CompetitionChart data={competition({ enough_data: false })} />);

    expect(screen.getByTestId("competition-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("competition-chart")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("competition-headline")
    ).not.toBeInTheDocument();
    // Even the thin-data state keeps the Arabic section title.
    expect(screen.getByText("ديناميكية المنافسة")).toBeInTheDocument();
  });
});
