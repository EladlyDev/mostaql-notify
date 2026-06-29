/// <reference types="vitest/globals" />
import { render, screen } from "@testing-library/react";

import type { Freshness, ScoreBreakdown, ScoreComponent } from "@/lib/types";
import { FreshnessBadge } from "@/components/score/FreshnessBadge";
import { ScoreBars } from "@/components/score/ScoreBars";
import { OutcomeBadge } from "@/components/score/OutcomeBadge";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function comp(over: Partial<ScoreComponent> = {}): ScoreComponent {
  return {
    key: "hiring_rate",
    label: "معدل التوظيف",
    raw: 90,
    sub_score: 0.75,
    weight: 0.35,
    contribution: 26,
    ...over,
  };
}

function breakdown(over: Partial<ScoreBreakdown> = {}): ScoreBreakdown {
  return {
    score: 70.8,
    normalized: false,
    computed_at: "2026-06-28T10:00:00Z",
    components: [comp()],
    ...over,
  };
}

// ---------------------------------------------------------------------------
// FreshnessBadge — exhaustive colour/label + null handling
// ---------------------------------------------------------------------------
describe("FreshnessBadge (exhaustive)", () => {
  const CASES: [Freshness, string, string][] = [
    ["green", "bg-emerald-500", "حديث ومنخفض المنافسة"],
    ["yellow", "bg-amber-500", "متوسط الحداثة"],
    ["red", "bg-red-500", "قديم أو مرتفع المنافسة"],
  ];

  it.each(CASES)(
    "%s -> colour %s, Arabic label, role=status, RTL-safe dot",
    (freshness, colourClass, label) => {
      const { container } = render(<FreshnessBadge freshness={freshness} />);
      const badge = container.querySelector(
        `[data-freshness="${freshness}"]`
      ) as HTMLElement | null;
      expect(badge).not.toBeNull();
      expect(badge?.getAttribute("role")).toBe("status");
      // Both title (hover) and aria-label carry the exact Arabic copy.
      expect(badge?.getAttribute("title")).toBe(label);
      expect(badge?.getAttribute("aria-label")).toBe(label);
      const dot = badge?.firstElementChild as HTMLElement | null;
      expect(dot?.className).toContain(colourClass);
      expect(dot?.className).toContain("rounded-full");
      // Dot is decorative — hidden from the a11y tree.
      expect(dot?.getAttribute("aria-hidden")).not.toBeNull();
    }
  );

  it("renders nothing for null freshness", () => {
    const { container } = render(<FreshnessBadge freshness={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing for an undefined-ish (falsy) freshness", () => {
    const { container } = render(
      <FreshnessBadge freshness={undefined as unknown as Freshness | null} />
    );
    expect(container.firstChild).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// ScoreBars — widths, clamping, empty, all-zero, fallback colour
// ---------------------------------------------------------------------------
describe("ScoreBars (exhaustive)", () => {
  function widthOf(bar: HTMLElement): string {
    const fill = bar.querySelector("div") as HTMLElement;
    return fill.style.width;
  }

  it("renders one bar per component, preserving model order", () => {
    const bd = breakdown({
      components: [
        comp({ key: "hiring_rate", label: "أ", contribution: 10 }),
        comp({ key: "competition", label: "ب", contribution: 20 }),
        comp({ key: "freshness", label: "ج", contribution: 30 }),
      ],
    });
    render(<ScoreBars breakdown={bd} />);
    const labels = screen
      .getAllByTestId("score-bar")
      .map((li) => li.querySelector("span")?.textContent);
    expect(labels).toEqual(["أ", "ب", "ج"]);
  });

  it("sets each bar width to the contribution percentage and aria-valuenow to its rounded value", () => {
    const bd = breakdown({
      components: [comp({ contribution: 26.4 })],
    });
    render(<ScoreBars breakdown={bd} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "26");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
    expect(widthOf(bar)).toBe("26.4%");
  });

  it("clamps contribution above 100 to 100%", () => {
    const bd = breakdown({ components: [comp({ contribution: 250 })] });
    render(<ScoreBars breakdown={bd} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "100");
    expect(widthOf(bar)).toBe("100%");
  });

  it("clamps negative contribution to 0%", () => {
    const bd = breakdown({ components: [comp({ contribution: -10 })] });
    render(<ScoreBars breakdown={bd} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "0");
    expect(widthOf(bar)).toBe("0%");
  });

  it("clamps non-finite contribution (NaN) to 0%", () => {
    const bd = breakdown({ components: [comp({ contribution: NaN })] });
    render(<ScoreBars breakdown={bd} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "0");
    expect(widthOf(bar)).toBe("0%");
  });

  it("renders all-zero contributions as 0%-width bars (no crash)", () => {
    const bd = breakdown({
      components: [
        comp({ key: "hiring_rate", label: "أ", contribution: 0 }),
        comp({ key: "budget", label: "ب", contribution: 0 }),
      ],
    });
    render(<ScoreBars breakdown={bd} />);
    const bars = screen.getAllByRole("progressbar");
    expect(bars).toHaveLength(2);
    bars.forEach((b) => {
      expect(b).toHaveAttribute("aria-valuenow", "0");
      expect(widthOf(b)).toBe("0%");
    });
  });

  it("shows the graceful note for an empty components array", () => {
    render(<ScoreBars breakdown={breakdown({ components: [] })} />);
    expect(screen.getByText("لا يوجد تفصيل للنقاط.")).toBeInTheDocument();
    expect(screen.queryByTestId("score-bar")).not.toBeInTheDocument();
  });

  it("shows the graceful note when components is null/undefined", () => {
    render(
      <ScoreBars
        breakdown={breakdown({
          components: undefined as unknown as ScoreComponent[],
        })}
      />
    );
    expect(screen.getByText("لا يوجد تفصيل للنقاط.")).toBeInTheDocument();
  });

  it("applies the known per-key hue and falls back to bg-primary for an unknown key", () => {
    const bd = breakdown({
      components: [
        comp({ key: "freshness", label: "ف", contribution: 5 }),
        comp({ key: "totally_unknown", label: "غ", contribution: 5 }),
      ],
    });
    render(<ScoreBars breakdown={bd} />);
    const fills = screen
      .getAllByRole("progressbar")
      .map((b) => (b.querySelector("div") as HTMLElement).className);
    expect(fills[0]).toContain("bg-violet-500");
    expect(fills[1]).toContain("bg-primary");
  });

  it("labels each progressbar with the component's Arabic label for a11y", () => {
    const bd = breakdown({ components: [comp({ label: "معدل التوظيف" })] });
    render(<ScoreBars breakdown={bd} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-label",
      "معدل التوظيف"
    );
  });
});

// ---------------------------------------------------------------------------
// OutcomeBadge — every outcome + fallback + null
// ---------------------------------------------------------------------------
describe("OutcomeBadge (exhaustive)", () => {
  const CASES: [string, string][] = [
    ["open", "مفتوح"],
    ["hired", "تم التوظيف"],
    ["closed_no_hire", "أُغلق دون توظيف"],
    ["unknown", "غير معروف"],
  ];

  it.each(CASES)("renders the Arabic label for outcome %s", (outcome, label) => {
    render(<OutcomeBadge outcome={outcome} />);
    const badge = screen.getByText(label);
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("aria-label", `المصير: ${label}`);
  });

  it("gives each known outcome a distinct className", () => {
    const classNames = CASES.map(([outcome, label]) => {
      const { unmount } = render(<OutcomeBadge outcome={outcome} />);
      const cls = screen.getByText(label).className;
      unmount();
      return cls;
    });
    expect(new Set(classNames).size).toBe(CASES.length);
  });

  it("falls back to the raw value for an unrecognised outcome", () => {
    render(<OutcomeBadge outcome="weird_state" />);
    const badge = screen.getByText("weird_state");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("aria-label", "المصير: weird_state");
  });

  it("renders nothing for a null outcome", () => {
    const { container } = render(<OutcomeBadge outcome={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for an empty-string outcome (falsy)", () => {
    const { container } = render(<OutcomeBadge outcome="" />);
    expect(container).toBeEmptyDOMElement();
  });
});
