/// <reference types="vitest/globals" />
import { render, screen } from "@testing-library/react";

import type {
  Lifecycle,
  ScoreBreakdown,
  Snapshot,
  StatusEvent,
} from "@/lib/types";
import { BidChart } from "@/components/lifecycle/BidChart";
import { StatusTimeline } from "@/components/lifecycle/StatusTimeline";
import { ScoreBars } from "@/components/score/ScoreBars";
import { OutcomeBadge } from "@/components/score/OutcomeBadge";

// ---------------------------------------------------------------------------
// These four are pure presentational components (props in, markup out): no
// TanStack query or API layer to mock. The detail-page wiring that DOES use the
// query/api layer (useLifecycle, revertAutoStatus) is covered by lib tests; here
// we exercise the rendering contract T026 pins down with mock lifecycle data.
// ---------------------------------------------------------------------------

// A climbing bid series + a status change — the US2 acceptance shape.
const LIFECYCLE: Lifecycle = {
  outcome: "open",
  snapshots: [
    {
      captured_at: "2026-06-28T08:00:00Z",
      bids_count: 5,
      site_status: "open",
      score: 70,
    },
    {
      captured_at: "2026-06-28T09:00:00Z",
      bids_count: 12,
      site_status: "open",
      score: 64,
    },
    {
      captured_at: "2026-06-28T10:00:00Z",
      bids_count: 20,
      site_status: "closed",
      score: 64,
    },
  ],
  status_timeline: [
    { at: "2026-06-28T08:00:00Z", status: "open" },
    { at: "2026-06-28T10:00:00Z", status: "closed" },
  ],
};

const BREAKDOWN: ScoreBreakdown = {
  score: 70.8,
  normalized: false,
  computed_at: "2026-06-28T10:00:00Z",
  components: [
    {
      key: "hiring_rate",
      label: "معدل التوظيف",
      raw: 90,
      sub_score: 0.7462,
      weight: 0.35,
      contribution: 26.12,
    },
    {
      key: "competition",
      label: "المنافسة",
      raw: 6,
      sub_score: 0.746,
      weight: 0.2,
      contribution: 14.92,
    },
    {
      key: "freshness",
      label: "الحداثة",
      raw: 9,
      sub_score: 0.5946,
      weight: 0.1,
      contribution: 5.95,
    },
  ],
};

// ---------------------------------------------------------------------------
// BidChart
// ---------------------------------------------------------------------------
describe("BidChart", () => {
  it("draws a sparkline (polyline + one dot per snapshot) for a climbing series", () => {
    const { container } = render(
      <BidChart snapshots={LIFECYCLE.snapshots} />
    );
    expect(screen.getByTestId("bid-chart")).toBeInTheDocument();
    expect(container.querySelector("polyline")).not.toBeNull();
    expect(screen.getAllByTestId("bid-point")).toHaveLength(3);
  });

  it("renders a lone dot and no polyline for a single observation", () => {
    const one: Snapshot[] = [LIFECYCLE.snapshots[0]];
    const { container } = render(<BidChart snapshots={one} />);
    expect(screen.getAllByTestId("bid-point")).toHaveLength(1);
    expect(container.querySelector("polyline")).toBeNull();
  });

  it("shows an empty-state note when there are no snapshots", () => {
    render(<BidChart snapshots={[]} />);
    expect(screen.getByTestId("bid-chart-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("bid-chart")).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// StatusTimeline
// ---------------------------------------------------------------------------
describe("StatusTimeline", () => {
  it("renders one stamped entry per transition with Arabic status labels", () => {
    render(<StatusTimeline events={LIFECYCLE.status_timeline} />);
    expect(screen.getAllByTestId("status-event")).toHaveLength(2);
    expect(screen.getByText("مفتوح")).toBeInTheDocument();
    expect(screen.getByText("مغلق")).toBeInTheDocument();
  });

  it("shows an empty-state note when there are no transitions", () => {
    const empty: StatusEvent[] = [];
    render(<StatusTimeline events={empty} />);
    expect(
      screen.getByText("لا توجد تغييرات في الحالة بعد.")
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// ScoreBars
// ---------------------------------------------------------------------------
describe("ScoreBars", () => {
  it("renders one bar per component, in order, with its Arabic label", () => {
    render(<ScoreBars breakdown={BREAKDOWN} />);
    const bars = screen.getAllByTestId("score-bar");
    expect(bars).toHaveLength(3);
    expect(screen.getByText("معدل التوظيف")).toBeInTheDocument();
    expect(screen.getByText("المنافسة")).toBeInTheDocument();
    expect(screen.getByText("الحداثة")).toBeInTheDocument();
  });

  it("exposes each bar as a progressbar whose value tracks its contribution", () => {
    render(<ScoreBars breakdown={BREAKDOWN} />);
    const bars = screen.getAllByRole("progressbar");
    expect(bars).toHaveLength(3);
    // First component contributes ~26 points out of 100.
    expect(bars[0]).toHaveAttribute("aria-valuenow", "26");
  });

  it("renders a graceful note when there are no components", () => {
    render(<ScoreBars breakdown={{ ...BREAKDOWN, components: [] }} />);
    expect(screen.getByText("لا يوجد تفصيل للنقاط.")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// OutcomeBadge
// ---------------------------------------------------------------------------
describe("OutcomeBadge", () => {
  it("shows the Arabic label for a hired outcome", () => {
    render(<OutcomeBadge outcome="hired" />);
    expect(screen.getByText("تم التوظيف")).toBeInTheDocument();
  });

  it("shows the Arabic label for a closed-without-hire outcome", () => {
    render(<OutcomeBadge outcome="closed_no_hire" />);
    expect(screen.getByText("أُغلق دون توظيف")).toBeInTheDocument();
  });

  it("renders nothing for a null outcome", () => {
    const { container } = render(<OutcomeBadge outcome={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
