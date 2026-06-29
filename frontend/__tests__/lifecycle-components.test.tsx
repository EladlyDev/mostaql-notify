/// <reference types="vitest/globals" />
import { render, screen } from "@testing-library/react";

import type { Snapshot, StatusEvent } from "@/lib/types";
import { BidChart } from "@/components/lifecycle/BidChart";
import { StatusTimeline } from "@/components/lifecycle/StatusTimeline";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function snap(over: Partial<Snapshot> = {}): Snapshot {
  return {
    captured_at: "2026-06-28T08:00:00Z",
    bids_count: 5,
    site_status: "open",
    score: 70,
    ...over,
  };
}

function pointsAt(bar: HTMLElement): { x: number; y: number }[] {
  return Array.from(bar.querySelectorAll("circle")).map((c) => ({
    x: Number(c.getAttribute("cx")),
    y: Number(c.getAttribute("cy")),
  }));
}

// ---------------------------------------------------------------------------
// BidChart
// ---------------------------------------------------------------------------
describe("BidChart (exhaustive)", () => {
  it("draws a polyline + one dot per snapshot for a monotonic climbing series", () => {
    const series = [
      snap({ captured_at: "2026-06-28T08:00:00Z", bids_count: 5 }),
      snap({ captured_at: "2026-06-28T09:00:00Z", bids_count: 12 }),
      snap({ captured_at: "2026-06-28T10:00:00Z", bids_count: 20 }),
    ];
    const { container } = render(<BidChart snapshots={series} />);
    expect(screen.getByTestId("bid-chart")).toBeInTheDocument();
    expect(container.querySelector("polyline")).not.toBeNull();
    expect(screen.getAllByTestId("bid-point")).toHaveLength(3);
  });

  it("handles a non-monotonic series (bids drop then rise) without crashing", () => {
    const series = [
      snap({ captured_at: "2026-06-28T08:00:00Z", bids_count: 10 }),
      snap({ captured_at: "2026-06-28T09:00:00Z", bids_count: 3 }),
      snap({ captured_at: "2026-06-28T10:00:00Z", bids_count: 18 }),
    ];
    const svg = render(<BidChart snapshots={series} />).getByTestId(
      "bid-chart"
    );
    const ys = pointsAt(svg).map((p) => p.y);
    // Highest bids (18) maps to the smallest y (top); lowest bids (3) to largest y.
    expect(Math.min(...ys)).toBe(ys[2]);
    expect(Math.max(...ys)).toBe(ys[1]);
    ys.forEach((y) => expect(Number.isFinite(y)).toBe(true));
  });

  it("renders a lone dot (larger radius) and no polyline for a single observation", () => {
    const { container } = render(<BidChart snapshots={[snap()]} />);
    const dots = screen.getAllByTestId("bid-point");
    expect(dots).toHaveLength(1);
    expect(dots[0].getAttribute("r")).toBe("4");
    expect(container.querySelector("polyline")).toBeNull();
  });

  it("shows the empty-state note (and no chart) for an empty array", () => {
    render(<BidChart snapshots={[]} />);
    expect(screen.getByTestId("bid-chart-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("bid-chart")).not.toBeInTheDocument();
  });

  it("treats null bids_count as 0 and still plots finite coordinates", () => {
    const series = [
      snap({ captured_at: "2026-06-28T08:00:00Z", bids_count: null }),
      snap({ captured_at: "2026-06-28T09:00:00Z", bids_count: 10 }),
      snap({ captured_at: "2026-06-28T10:00:00Z", bids_count: null }),
    ];
    const svg = render(<BidChart snapshots={series} />).getByTestId(
      "bid-chart"
    );
    const pts = pointsAt(svg);
    expect(pts).toHaveLength(3);
    pts.forEach((p) => {
      expect(Number.isFinite(p.x)).toBe(true);
      expect(Number.isFinite(p.y)).toBe(true);
    });
    // The two null (=> 0 bids) points sit at the chart floor (same, largest y).
    expect(pts[0].y).toBe(pts[2].y);
    expect(pts[1].y).toBeLessThan(pts[0].y);
  });

  it("collapses identical timestamps (zero time span) without producing NaN x", () => {
    const series = [
      snap({ captured_at: "2026-06-28T08:00:00Z", bids_count: 4 }),
      snap({ captured_at: "2026-06-28T08:00:00Z", bids_count: 9 }),
    ];
    const svg = render(<BidChart snapshots={series} />).getByTestId(
      "bid-chart"
    );
    pointsAt(svg).forEach((p) => expect(Number.isFinite(p.x)).toBe(true));
  });

  it("exposes an Arabic aria-label spanning the earliest→latest bid counts", () => {
    const series = [
      snap({ captured_at: "2026-06-28T08:00:00Z", bids_count: 5 }),
      snap({ captured_at: "2026-06-28T10:00:00Z", bids_count: 20 }),
    ];
    const svg = render(<BidChart snapshots={series} />).getByTestId(
      "bid-chart"
    );
    expect(svg.getAttribute("aria-label")).toContain("مسار العروض");
    expect(svg.getAttribute("role")).toBe("img");
  });
});

// ---------------------------------------------------------------------------
// StatusTimeline
// ---------------------------------------------------------------------------
describe("StatusTimeline (exhaustive)", () => {
  it("renders deduped transitions in order with Arabic labels + coloured dots", () => {
    const events: StatusEvent[] = [
      { at: "2026-06-28T08:00:00Z", status: "open" },
      { at: "2026-06-28T10:00:00Z", status: "closed" },
      { at: "2026-06-28T12:00:00Z", status: "awarded" },
    ];
    render(<StatusTimeline events={events} />);
    const items = screen.getAllByTestId("status-event");
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toContain("مفتوح");
    expect(items[1].textContent).toContain("مغلق");
    expect(items[2].textContent).toContain("تم الإسناد");
  });

  it("renders a single event", () => {
    render(
      <StatusTimeline events={[{ at: "2026-06-28T08:00:00Z", status: "open" }]} />
    );
    expect(screen.getAllByTestId("status-event")).toHaveLength(1);
    expect(screen.getByText("مفتوح")).toBeInTheDocument();
  });

  it("shows the empty-state note for an empty array", () => {
    render(<StatusTimeline events={[]} />);
    expect(
      screen.getByText("لا توجد تغييرات في الحالة بعد.")
    ).toBeInTheDocument();
    expect(screen.queryByTestId("status-event")).not.toBeInTheDocument();
  });

  it("shows the empty-state note when events is null/undefined", () => {
    render(
      <StatusTimeline events={null as unknown as StatusEvent[]} />
    );
    expect(
      screen.getByText("لا توجد تغييرات في الحالة بعد.")
    ).toBeInTheDocument();
  });

  it("does not crash on consecutive duplicate statuses (renders each given entry)", () => {
    const events: StatusEvent[] = [
      { at: "2026-06-28T08:00:00Z", status: "open" },
      { at: "2026-06-28T09:00:00Z", status: "open" },
    ];
    render(<StatusTimeline events={events} />);
    expect(screen.getAllByTestId("status-event")).toHaveLength(2);
  });

  it("falls back to the raw status string for an unrecognised status", () => {
    render(
      <StatusTimeline
        events={[{ at: "2026-06-28T08:00:00Z", status: "frozen" }]}
      />
    );
    expect(screen.getByText("frozen")).toBeInTheDocument();
  });
});
