/// <reference types="vitest/globals" />
import { render, screen } from "@testing-library/react";

import type { Funnel, FunnelStage } from "@/lib/types";
import { FunnelChart } from "@/components/analytics/FunnelChart";

// ---------------------------------------------------------------------------
// Typed fixture factories.
// ---------------------------------------------------------------------------
function stage(over: Partial<FunnelStage> = {}): FunnelStage {
  return {
    key: "seen",
    label: "ظهور",
    count: 100,
    conv_from_prev: null,
    lag_median_hours: null,
    ...over,
  };
}

function funnel(over: Partial<Funnel> = {}): Funnel {
  return {
    stages: [
      // The seen stage anchors the funnel: no previous → null conv, null lag.
      stage({ key: "seen", label: "ظهور", count: 100 }),
      stage({
        key: "favourited",
        label: "مفضّل",
        count: 40,
        conv_from_prev: 0.4,
        lag_median_hours: 2,
      }),
      stage({
        key: "applied",
        label: "تقديم",
        count: 20,
        conv_from_prev: 0.5,
        lag_median_hours: 5,
      }),
      stage({
        key: "won",
        label: "فوز",
        count: 5,
        conv_from_prev: 0.25,
        lag_median_hours: 12,
      }),
    ],
    seen: 100,
    enough_data: true,
    ...over,
  };
}

describe("FunnelChart", () => {
  it("renders one stage per funnel stage, with conversion % and lag", () => {
    render(<FunnelChart data={funnel()} />);

    expect(screen.getByTestId("funnel-chart")).toBeInTheDocument();
    expect(screen.queryByTestId("funnel-empty")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("funnel-stage")).toHaveLength(4);

    // Stage labels render.
    expect(screen.getByText("ظهور")).toBeInTheDocument();
    expect(screen.getByText("مفضّل")).toBeInTheDocument();
    expect(screen.getByText("فوز")).toBeInTheDocument();

    // The seen stage: null conv → "—" and null lag → "غير متاح" (exactly one each).
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("غير متاح")).toBeInTheDocument();
  });

  it("shows the not-enough-data state (and no chart) when enough_data is false", () => {
    render(<FunnelChart data={funnel({ enough_data: false, stages: [], seen: 0 })} />);

    expect(screen.getByTestId("funnel-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("funnel-chart")).not.toBeInTheDocument();
    expect(screen.queryAllByTestId("funnel-stage")).toHaveLength(0);
  });
});
