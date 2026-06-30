/// <reference types="vitest/globals" />
import { render, screen } from "@testing-library/react";

import type { MissedProject, OutcomeAnalytics } from "@/lib/types";
import { OutcomesPanel } from "@/components/analytics/OutcomesPanel";

// ---------------------------------------------------------------------------
// Typed fixture factories.
// ---------------------------------------------------------------------------
function missed(over: Partial<MissedProject> = {}): MissedProject {
  return {
    id: 1,
    title: "مشروع فائت",
    url: "https://example.com/p/1",
    budget_usd: 500,
    ...over,
  };
}

function outcomes(over: Partial<OutcomeAnalytics> = {}): OutcomeAnalytics {
  return {
    hired_count: 6,
    no_hire_count: 4,
    unknown_count: 2,
    open_count: 3,
    hired_share: 0.6,
    no_hire_share: 0.4,
    time_to_close_hours: { mean: 48, median: 36, p25: 24, p75: 60 },
    missed: [
      missed({ id: 1, title: "مشروع فائت" }),
      missed({ id: 2, title: "فرصة ثانية", budget_usd: null }),
    ],
    missed_count: 2,
    enough_data: true,
    ...over,
  };
}

describe("OutcomesPanel", () => {
  it("renders Part A shares + time-to-close and the missed list when enough data", () => {
    render(<OutcomesPanel data={outcomes()} />);

    expect(screen.getByTestId("outcomes-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("outcomes-empty")).not.toBeInTheDocument();

    // Part A — hired vs no-hire legend + time-to-close labels.
    expect(screen.getByText("تم التوظيف")).toBeInTheDocument();
    expect(screen.getByText("أُغلق دون توظيف")).toBeInTheDocument();
    expect(screen.getByText("الوسطي")).toBeInTheDocument();
    expect(screen.getByText("الوسيط (أكثر متانة)")).toBeInTheDocument();

    // Part B — one linked row per missed opportunity.
    const list = screen.getByTestId("missed-list");
    expect(list.querySelectorAll("li")).toHaveLength(2);
    expect(screen.getByText("مشروع فائت")).toBeInTheDocument();
    expect(screen.getByText("فرصة ثانية")).toBeInTheDocument();
  });

  it("shows the Part A empty state but STILL renders the missed list when enough_data is false", () => {
    render(<OutcomesPanel data={outcomes({ enough_data: false })} />);

    // Part A collapses to the honest not-enough-data note...
    expect(screen.getByTestId("outcomes-empty")).toBeInTheDocument();
    // ...while Part B (missed opportunities) is always rendered.
    expect(screen.getByTestId("missed-list")).toBeInTheDocument();
    expect(screen.getByTestId("missed-list").querySelectorAll("li")).toHaveLength(
      2
    );
  });

  it("renders the Part B 'no missed' note (and no list) when there are none", () => {
    render(<OutcomesPanel data={outcomes({ missed: [], missed_count: 0 })} />);

    expect(screen.queryByTestId("missed-list")).not.toBeInTheDocument();
    expect(screen.getByText("لا توجد فرص فائتة — أحسنت")).toBeInTheDocument();
  });
});
