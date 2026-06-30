/// <reference types="vitest/globals" />
import { render, screen } from "@testing-library/react";

import type { Tip } from "@/lib/types";
import { TipsPanel } from "@/components/analytics/TipsPanel";

// ---------------------------------------------------------------------------
// Typed fixture factory.
// ---------------------------------------------------------------------------
function tip(over: Partial<Tip> = {}): Tip {
  return {
    key: "peak_window",
    text: "أفضل وقت للنشر هو مساء الأحد",
    evidence: {},
    ...over,
  };
}

describe("TipsPanel", () => {
  it("renders one tip-item per tip (incl. an unknown key with the fallback icon)", () => {
    const tips: Tip[] = [
      tip({ key: "peak_window", text: "أفضل وقت للنشر هو مساء الأحد" }),
      tip({ key: "bid_speed", text: "قدّم خلال أول ساعة لرفع فرصك" }),
      tip({ key: "unknown_future_key", text: "نصيحة بمفتاح غير معروف" }),
    ];
    render(<TipsPanel tips={tips} />);

    expect(screen.getByTestId("tips-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("tips-empty")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("tip-item")).toHaveLength(3);

    expect(screen.getByText("أفضل وقت للنشر هو مساء الأحد")).toBeInTheDocument();
    expect(screen.getByText("قدّم خلال أول ساعة لرفع فرصك")).toBeInTheDocument();
    expect(screen.getByText("نصيحة بمفتاح غير معروف")).toBeInTheDocument();
  });

  it("shows the empty state (and no list) when tips is empty", () => {
    render(<TipsPanel tips={[]} />);

    expect(screen.getByTestId("tips-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("tips-panel")).not.toBeInTheDocument();
    expect(screen.queryAllByTestId("tip-item")).toHaveLength(0);
    expect(screen.getByText("لا توجد نصائح كافية بعد")).toBeInTheDocument();
  });
});
