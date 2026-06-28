/// <reference types="vitest/globals" />
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type {
  PersonalRecord,
  PersonalStatusOption,
  ProjectListItem,
} from "@/lib/types";
import { ProjectRowMenu } from "@/components/personal/ProjectRowMenu";

// ---------------------------------------------------------------------------
// Mock the API module so the mutation functions are spies we can assert on.
// `vi.hoisted` keeps the spy references usable inside the hoisted vi.mock.
// ---------------------------------------------------------------------------
const { toggleFavoriteSpy, updatePersonalSpy, getPersonalSpy } = vi.hoisted(
  () => ({
    toggleFavoriteSpy: vi.fn(),
    updatePersonalSpy: vi.fn(),
    getPersonalSpy: vi.fn(),
  })
);

vi.mock("@/lib/api", () => ({
  toggleFavorite: toggleFavoriteSpy,
  updatePersonal: updatePersonalSpy,
  getPersonal: getPersonalSpy,
}));

// ---------------------------------------------------------------------------
// jsdom polyfills required by the Base UI popup/positioner internals.
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

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
const STATUSES: PersonalStatusOption[] = [
  { key: "lead", label: "عميل محتمل" },
  { key: "applied", label: "تم التقديم" },
  { key: "won", label: "تم الفوز" },
  { key: "lost", label: "خسارة" },
];

const RECORD: PersonalRecord = {
  project_id: 42,
  favorite: false,
  status: "lead",
  status_label: "عميل محتمل",
  tags: [],
  applied_at: null,
  won_amount: null,
  lost_reason: null,
  notes: "",
  board_position: 0,
  hidden: false,
  status_changed_at: null,
  reminder_at: null,
};

function makeItem(overrides: Partial<ProjectListItem> = {}): ProjectListItem {
  return {
    id: 42,
    title: "مشروع تجريبي",
    url: "https://example.com/p/42",
    client_name: "عميل",
    client_hiring_rate: 80,
    budget_min: 100,
    budget_max: 200,
    currency: "USD",
    tier: 1,
    tier_label: "Tier 1",
    bids_count: 3,
    posted_at: null,
    site_status: "open",
    eval_status: "qualified",
    qualified: true,
    favorite: false,
    personal_status: "lead",
    personal_status_label: "عميل محتمل",
    tags: [],
    hidden: false,
    ...overrides,
  };
}

function renderMenu(item: ProjectListItem) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ProjectRowMenu item={item} statuses={STATUSES} defaultOpen />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  toggleFavoriteSpy.mockResolvedValue(RECORD);
  updatePersonalSpy.mockResolvedValue(RECORD);
  getPersonalSpy.mockResolvedValue(RECORD);
});

describe("ProjectRowMenu", () => {
  it("renders the quick actions (favorite, status, hide)", () => {
    renderMenu(makeItem());
    expect(screen.getByText("إضافة إلى المفضّلة")).toBeInTheDocument();
    expect(screen.getByText("الحالة")).toBeInTheDocument();
    expect(screen.getByText("إخفاء المشروع")).toBeInTheDocument();
  });

  it("lists every configured status label in the submenu (config-driven)", () => {
    renderMenu(makeItem());
    for (const s of STATUSES) {
      expect(screen.getByText(s.label)).toBeInTheDocument();
    }
  });

  it("toggles favorite with the project id", async () => {
    renderMenu(makeItem());
    fireEvent.click(screen.getByText("إضافة إلى المفضّلة"));
    await waitFor(() => {
      expect(toggleFavoriteSpy).toHaveBeenCalledWith(42);
    });
    expect(updatePersonalSpy).not.toHaveBeenCalled();
  });

  it("sets the status with the selected stage key", async () => {
    renderMenu(makeItem());
    fireEvent.click(screen.getByText("تم التقديم"));
    await waitFor(() => {
      expect(updatePersonalSpy).toHaveBeenCalledWith(42, { status: "applied" });
    });
    expect(toggleFavoriteSpy).not.toHaveBeenCalled();
  });

  it("hides a visible project", async () => {
    renderMenu(makeItem({ hidden: false }));
    fireEvent.click(screen.getByText("إخفاء المشروع"));
    await waitFor(() => {
      expect(updatePersonalSpy).toHaveBeenCalledWith(42, { hidden: true });
    });
  });

  it("unhides a hidden project", async () => {
    renderMenu(makeItem({ hidden: true }));
    fireEvent.click(screen.getByText("إظهار المشروع"));
    await waitFor(() => {
      expect(updatePersonalSpy).toHaveBeenCalledWith(42, { hidden: false });
    });
  });
});
