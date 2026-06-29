/// <reference types="vitest/globals" />
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { ProjectListItem } from "@/lib/types";
import type { ProjectParams, UseProjectsResult } from "@/lib/useProjects";

// ---------------------------------------------------------------------------
// Mock the data layer so the feed components don't hit the network. Only the
// functions the rendered tree touches on mount need to be present.
// ---------------------------------------------------------------------------
const { getStatusesSpy } = vi.hoisted(() => ({ getStatusesSpy: vi.fn() }));

vi.mock("@/lib/api", () => ({
  getStatuses: getStatusesSpy,
  toggleFavorite: vi.fn(),
  updatePersonal: vi.fn(),
  getPersonal: vi.fn(),
}));

import { ProjectTable } from "@/components/ProjectTable";
import { Filters } from "@/components/Filters";

// ---------------------------------------------------------------------------
// jsdom polyfills required by the Base UI Select / popup internals.
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
  getStatusesSpy.mockResolvedValue([]);
});

function makeItem(overrides: Partial<ProjectListItem> = {}): ProjectListItem {
  return {
    id: 1,
    title: "مشروع",
    url: "https://example.com/p/1",
    client_name: "عميل",
    client_hiring_rate: 80,
    budget_min: 100,
    budget_max: 200,
    currency: "USD",
    tier: 1,
    tier_label: "Tier 1",
    bids_count: 4,
    posted_at: null,
    site_status: "open",
    eval_status: "qualified",
    qualified: true,
    favorite: false,
    personal_status: "lead",
    personal_status_label: "عميل محتمل",
    tags: [],
    hidden: false,
    score: null,
    freshness: null,
    ...overrides,
  };
}

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const arabic = (n: number) => new Intl.NumberFormat("ar-EG").format(n);

describe("ProjectTable — score column", () => {
  it("renders a score header, the rounded score value, and a freshness dot", () => {
    const items = [
      makeItem({ id: 1, score: 86.6, freshness: "green" }),
      makeItem({ id: 2, score: null, freshness: null }),
    ];
    const { container } = renderWithClient(<ProjectTable items={items} />);

    // Score column header.
    expect(screen.getByText("التقييم")).toBeInTheDocument();
    // Rounded score for the scored row (86.6 → 87, Arabic-Indic digits).
    expect(container.textContent).toContain(arabic(87));
    // Exactly one freshness dot — the unscored row has none.
    const dots = container.querySelectorAll("[data-freshness]");
    expect(dots).toHaveLength(1);
    expect(dots[0].getAttribute("data-freshness")).toBe("green");
  });
});

describe("Filters — score sort + score range", () => {
  function makeController(
    over: Partial<UseProjectsResult> = {},
    params: Partial<ProjectParams> = {}
  ): UseProjectsResult {
    return {
      params: {
        sort: "posted_at",
        order: "desc",
        page: 1,
        page_size: 25,
        ...params,
      },
      filtersActive: false,
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      setFilters: vi.fn(),
      setSort: vi.fn(),
      setPage: vi.fn(),
      clearFilters: vi.fn(),
      ...over,
    };
  }

  it("commits the score-range bounds through setFilters", () => {
    const setFilters = vi.fn();
    const controller = makeController({ setFilters });
    renderWithClient(<Filters controller={controller} />);

    const min = screen.getByLabelText("أدنى تقييم");
    fireEvent.change(min, { target: { value: "70" } });
    fireEvent.blur(min);
    expect(setFilters).toHaveBeenCalledWith({ score_min: 70 });

    const max = screen.getByLabelText("أعلى تقييم");
    fireEvent.change(max, { target: { value: "95" } });
    fireEvent.blur(max);
    expect(setFilters).toHaveBeenCalledWith({ score_max: 95 });
  });

  it("sorts by score when the score option is chosen", async () => {
    const setSort = vi.fn();
    const controller = makeController({ setSort });
    renderWithClient(<Filters controller={controller} />);

    // Open the sort Select and pick the score option ("التقييم"). Base UI
    // commits the selection on the full pointer sequence over the option.
    fireEvent.click(screen.getByLabelText("الترتيب حسب"));
    const option = await screen.findByRole("option", { name: "التقييم" });
    fireEvent.pointerDown(option);
    fireEvent.pointerUp(option);
    fireEvent.click(option);

    await waitFor(() => expect(setSort).toHaveBeenCalledWith("score"));
  });
});
