/// <reference types="vitest/globals" />
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { AnalyticsOverview } from "@/lib/types";

// ---------------------------------------------------------------------------
// Mock the data layer and the Next navigation hooks the page tree touches.
// `getAnalyticsOverview` is overridden (the rest of `@/lib/api`, incl. ApiError
// which the page imports, stays real). `next/navigation` is fully stubbed.
// ---------------------------------------------------------------------------
const { getOverviewSpy, pushSpy } = vi.hoisted(() => ({
  getOverviewSpy: vi.fn(),
  pushSpy: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, getAnalyticsOverview: getOverviewSpy };
});

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: pushSpy }),
  usePathname: () => "/analytics",
}));

import AnalyticsPage from "@/app/analytics/page";

// ---------------------------------------------------------------------------
// jsdom polyfills required by the Base UI Tabs / ToggleGroup internals that the
// page tree (VolumeChart, DateRangeFilter) mounts.
// ---------------------------------------------------------------------------
beforeAll(() => {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver =
    ResizeObserverStub as unknown as typeof ResizeObserver;

  class IntersectionObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  }
  globalThis.IntersectionObserver =
    IntersectionObserverStub as unknown as typeof IntersectionObserver;

  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });

  Element.prototype.scrollIntoView = () => {};
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
});

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Fixtures — a complete, valid overview and an all-empty one.
// ---------------------------------------------------------------------------
function weekdayLabels(): string[] {
  return [
    "السبت",
    "الأحد",
    "الاثنين",
    "الثلاثاء",
    "الأربعاء",
    "الخميس",
    "الجمعة",
  ];
}

function fullOverview(): AnalyticsOverview {
  return {
    range: {
      date_from: "2026-06-01",
      date_to: "2026-06-30",
      timezone: "Africa/Cairo",
      default_applied: false,
    },
    heatmap: {
      cells: [{ weekday: 1, hour: 20, count: 7 }],
      weekday_labels: weekdayLabels(),
      total: 7,
      peak: { weekday: 1, hour: 20, count: 7 },
      enough_data: true,
    },
    volume: {
      by_day: [
        { period: "2026-06-28", total: 10, qualified: 4 },
        { period: "2026-06-29", total: 8, qualified: 3 },
      ],
      by_week: [{ period: "2026-W26", total: 18, qualified: 7 }],
      category: "all",
      enough_data: true,
    },
    budget: {
      buckets: [
        { lo: 0, hi: 100, count: 3 },
        { lo: 100, hi: null, count: 2 },
        { lo: null, hi: null, count: 1 },
      ],
      tier1_count: 4,
      tier2_count: 2,
      unknown_count: 1,
      total: 7,
      enough_data: true,
    },
    competition: {
      age_curve: [
        { age_lo_h: 0, age_hi_h: 6, median: 3, p25: 1, p75: 5, n: 12 },
        { age_lo_h: 6, age_hi_h: 9999, median: 8, p25: 5, p75: 12, n: 8 },
      ],
      crowded_bids: 10,
      crowded_after_hours: 6,
      headline: "تزداد المنافسة بسرعة بعد ٦ ساعات",
      by_hour: Array.from({ length: 24 }, () => 1),
      enough_data: true,
    },
    outcomes: {
      hired_count: 6,
      no_hire_count: 4,
      unknown_count: 2,
      open_count: 3,
      hired_share: 0.6,
      no_hire_share: 0.4,
      time_to_close_hours: { mean: 48, median: 36, p25: 24, p75: 60 },
      missed: [
        {
          id: 11,
          title: "فرصة فائتة",
          url: "https://example.com/p/11",
          budget_usd: 500,
        },
      ],
      missed_count: 1,
      enough_data: true,
    },
    funnel: {
      stages: [
        { key: "seen", label: "ظهور", count: 100, conv_from_prev: null, lag_median_hours: null },
        { key: "favourited", label: "مفضّل", count: 40, conv_from_prev: 0.4, lag_median_hours: 2 },
        { key: "applied", label: "تقديم", count: 20, conv_from_prev: 0.5, lag_median_hours: 5 },
        { key: "won", label: "فوز", count: 5, conv_from_prev: 0.25, lag_median_hours: 12 },
      ],
      seen: 100,
      enough_data: true,
    },
    tips: [
      { key: "peak_window", text: "أفضل وقت للنشر هو مساء الأحد", evidence: {} },
      { key: "bid_speed", text: "قدّم بسرعة لرفع فرصك", evidence: {} },
    ],
  };
}

/** Every section empty + all-zero totals ⇒ the page's range-empty gate fires. */
function emptyOverview(): AnalyticsOverview {
  return {
    range: {
      date_from: "2026-06-01",
      date_to: "2026-06-30",
      timezone: "Africa/Cairo",
      default_applied: true,
    },
    heatmap: {
      cells: [],
      weekday_labels: weekdayLabels(),
      total: 0,
      peak: null,
      enough_data: false,
    },
    volume: { by_day: [], by_week: [], category: "all", enough_data: false },
    budget: {
      buckets: [],
      tier1_count: 0,
      tier2_count: 0,
      unknown_count: 0,
      total: 0,
      enough_data: false,
    },
    competition: {
      age_curve: [],
      crowded_bids: 0,
      crowded_after_hours: null,
      headline: "",
      by_hour: Array.from({ length: 24 }, () => 0),
      enough_data: false,
    },
    outcomes: {
      hired_count: 0,
      no_hire_count: 0,
      unknown_count: 0,
      open_count: 0,
      hired_share: null,
      no_hire_share: null,
      time_to_close_hours: { mean: null, median: null, p25: null, p75: null },
      missed: [],
      missed_count: 0,
      enough_data: false,
    },
    funnel: { stages: [], seen: 0, enough_data: false },
    tips: [],
  };
}

/**
 * Range has data (heatmap.total > 0 ⇒ NOT range-empty) but every section is
 * below its own support threshold ⇒ each card shows its own empty gate.
 */
function thinSectionsOverview(): AnalyticsOverview {
  const o = emptyOverview();
  return { ...o, heatmap: { ...o.heatmap, total: 5 } };
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AnalyticsPage />
    </QueryClientProvider>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe("AnalyticsPage", () => {
  it("renders the date-range filter and every section card once the overview loads", async () => {
    getOverviewSpy.mockResolvedValue(fullOverview());
    renderPage();

    // The filter sits outside the data-gated body, so it appears straight away.
    expect(await screen.findByTestId("date-range-filter")).toBeInTheDocument();

    // All seven section cards render after the overview resolves.
    expect(await screen.findByTestId("heatmap")).toBeInTheDocument();
    expect(await screen.findByTestId("outcomes-panel")).toBeInTheDocument();
    expect(await screen.findByTestId("funnel-chart")).toBeInTheDocument();
    expect(await screen.findByTestId("tips-panel")).toBeInTheDocument();

    // Section card titles.
    expect(screen.getByText("خريطة أوقات النشر")).toBeInTheDocument();
    expect(screen.getByText("حجم المشاريع")).toBeInTheDocument();
    expect(screen.getByText("توزيع الميزانيات")).toBeInTheDocument();
    expect(screen.getByText("ديناميكية المنافسة")).toBeInTheDocument();
    expect(screen.getByText("نتائج المشاريع")).toBeInTheDocument();
    expect(screen.getByText("مسار التحويل")).toBeInTheDocument();
    expect(screen.getByText("نصائح وملاحظات")).toBeInTheDocument();

    expect(getOverviewSpy).toHaveBeenCalled();
  });

  it("shows the range-empty message (not the section cards) when the range has no data", async () => {
    getOverviewSpy.mockResolvedValue(emptyOverview());
    renderPage();

    expect(
      await screen.findByText("لا توجد بيانات في النطاق المحدّد")
    ).toBeInTheDocument();

    // The per-section cards are short-circuited by the range-empty state.
    expect(screen.queryByTestId("outcomes-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("funnel-chart")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tips-panel")).not.toBeInTheDocument();

    // The filter remains available so the range can be widened.
    expect(screen.getByTestId("date-range-filter")).toBeInTheDocument();
  });

  it("falls back to each section's own empty state when the range has data but sections are thin", async () => {
    getOverviewSpy.mockResolvedValue(thinSectionsOverview());
    renderPage();

    // Not range-empty (heatmap.total > 0) ⇒ cards render their own gates.
    expect(await screen.findByTestId("heatmap-empty")).toBeInTheDocument();
    expect(screen.getByTestId("outcomes-empty")).toBeInTheDocument();
    expect(screen.getByTestId("funnel-empty")).toBeInTheDocument();
    expect(screen.getByTestId("tips-empty")).toBeInTheDocument();

    expect(
      screen.queryByText("لا توجد بيانات في النطاق المحدّد")
    ).not.toBeInTheDocument();
  });
});
