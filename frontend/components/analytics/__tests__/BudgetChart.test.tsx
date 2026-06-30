/// <reference types="vitest/globals" />
import { render, screen } from "@testing-library/react";

import type { BudgetBucket, BudgetDistribution } from "@/lib/types";
import { BudgetChart } from "@/components/analytics/BudgetChart";

// ---------------------------------------------------------------------------
// Fixture factory
// ---------------------------------------------------------------------------
function bucket(over: Partial<BudgetBucket> = {}): BudgetBucket {
  return { lo: 0, hi: 50, count: 1, ...over };
}

function budget(over: Partial<BudgetDistribution> = {}): BudgetDistribution {
  return {
    buckets: [
      bucket({ lo: 0, hi: 50, count: 5 }),
      bucket({ lo: 50, hi: 200, count: 12 }),
      bucket({ lo: 200, hi: null, count: 4 }),
      bucket({ lo: null, hi: null, count: 3 }),
    ],
    tier1_count: 14,
    tier2_count: 6,
    unknown_count: 4,
    total: 24,
    enough_data: true,
    ...over,
  };
}

// ---------------------------------------------------------------------------
// BudgetChart
// ---------------------------------------------------------------------------
describe("BudgetChart", () => {
  it("renders the chart, histogram, one bar per bucket and the Arabic title", () => {
    render(<BudgetChart data={budget()} />);

    expect(screen.getByText("توزيع الميزانيات")).toBeInTheDocument();
    expect(screen.getByTestId("budget-chart")).toBeInTheDocument();
    expect(screen.getByTestId("budget-histogram")).toBeInTheDocument();
    expect(screen.getAllByTestId("budget-bar")).toHaveLength(4);
  });

  it("renders the tier split with Arabic labels and percentages", () => {
    render(<BudgetChart data={budget()} />);

    const tiers = screen.getByTestId("budget-tiers");
    expect(tiers).toBeInTheDocument();

    expect(screen.getByText("الفئة الأولى")).toBeInTheDocument();
    expect(screen.getByText("الفئة الثانية")).toBeInTheDocument();
    expect(screen.getByText("غير محددة")).toBeInTheDocument();

    // Each tier shows a share rendered as an Arabic percentage (U+066A "٪").
    expect(tiers.textContent ?? "").toContain("٪");
  });

  it("labels the unknown / partial-budget band in Arabic", () => {
    render(<BudgetChart data={budget()} />);
    expect(screen.getByText("غير معروفة")).toBeInTheDocument();
  });

  it("shows the empty state (and no chart) when enough_data is false", () => {
    render(<BudgetChart data={budget({ enough_data: false })} />);

    expect(screen.getByTestId("budget-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("budget-chart")).not.toBeInTheDocument();
    expect(screen.queryByTestId("budget-histogram")).not.toBeInTheDocument();
  });
});
