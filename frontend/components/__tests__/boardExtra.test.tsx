/// <reference types="vitest/globals" />
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import type { BoardCard, BoardResponse } from "@/lib/types";

// ---------------------------------------------------------------------------
// Stub dnd-kit primitives so rendering doesn't need a live drag context (same
// approach as board.test.tsx — kept here only to render the board statically).
// This file covers presentation details board.test.tsx does NOT assert.
// ---------------------------------------------------------------------------
vi.mock("@dnd-kit/core", () => ({
  DndContext: ({ children }: { children: ReactNode }) => children,
  useDroppable: () => ({ setNodeRef: () => {}, isOver: false }),
  useSensor: () => ({}),
  useSensors: (...sensors: unknown[]) => sensors,
  PointerSensor: function PointerSensor() {},
  KeyboardSensor: function KeyboardSensor() {},
  closestCorners: () => null,
}));

vi.mock("@dnd-kit/sortable", () => ({
  SortableContext: ({ children }: { children: ReactNode }) => children,
  useSortable: () => ({
    attributes: {},
    listeners: {},
    setNodeRef: () => {},
    transform: null,
    transition: undefined,
    isDragging: false,
  }),
  sortableKeyboardCoordinates: () => {},
  verticalListSortingStrategy: {},
}));

vi.mock("@dnd-kit/utilities", () => ({
  CSS: { Transform: { toString: () => "" } },
}));

const { getBoardMock, moveBoardCardMock } = vi.hoisted(() => ({
  getBoardMock: vi.fn(),
  moveBoardCardMock: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  getBoard: getBoardMock,
  moveBoardCard: moveBoardCardMock,
}));

import { Board } from "@/components/board/Board";

function makeCard(
  project_id: number,
  overrides: Partial<BoardCard> = {}
): BoardCard {
  return {
    project_id,
    title: `مشروع ${project_id}`,
    url: null,
    client_hiring_rate: 80,
    budget_min: 100,
    budget_max: 200,
    currency: "USD",
    tier: 1,
    tier_label: "المستوى الأول",
    bids_count: 3,
    posted_at: "2026-06-27T10:00:00Z",
    tags: ["عاجل"],
    status: "new",
    board_position: 0,
    ...overrides,
  };
}

function renderBoard(board: BoardResponse) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <Board board={board} />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  getBoardMock.mockReset().mockResolvedValue({ columns: [] });
  moveBoardCardMock.mockReset();
});

describe("Board card facts", () => {
  it("renders a card's title, budget currency, meta labels, tier, and tags", () => {
    renderBoard({
      columns: [
        {
          key: "new",
          label: "جديد",
          cards: [makeCard(101, { title: "مشروع أ", tags: ["عاجل", "تصميم"] })],
        },
      ],
    });

    const region = screen.getByRole("region", { name: "جديد" });

    // Title (linked).
    expect(within(region).getByText("مشروع أ")).toBeInTheDocument();
    // Meta field labels.
    expect(within(region).getByText("نسبة التوظيف")).toBeInTheDocument();
    expect(within(region).getByText("الميزانية")).toBeInTheDocument();
    expect(within(region).getByText("العروض")).toBeInTheDocument();
    expect(within(region).getByText("النشر")).toBeInTheDocument();
    // Budget currency shows in the rendered budget string.
    expect(region.textContent).toContain("USD");
    // Tier badge + tag badges.
    expect(within(region).getByText("المستوى الأول")).toBeInTheDocument();
    expect(within(region).getByText("عاجل")).toBeInTheDocument();
    expect(within(region).getByText("تصميم")).toBeInTheDocument();
  });

  it("links each card to its project detail page", () => {
    renderBoard({
      columns: [{ key: "new", label: "جديد", cards: [makeCard(555)] }],
    });
    const link = screen.getByRole("link", { name: /مشروع 555/ });
    expect(link).toHaveAttribute("href", "/projects/555");
  });
});

describe("Board column rendering", () => {
  it("renders an empty column header with a zero (Arabic-Indic) count and a placeholder", () => {
    renderBoard({
      columns: [
        { key: "new", label: "جديد", cards: [makeCard(1)] },
        { key: "won", label: "فاز", cards: [] },
      ],
    });
    const empty = screen.getByRole("region", { name: "فاز" });
    // formatNumber(0) → Arabic-Indic zero ٠ in the count badge.
    expect(empty.textContent).toContain("٠");
    // Placeholder body so the empty column is still a drop target.
    expect(within(empty).getByText("لا توجد مشاريع")).toBeInTheDocument();
  });

  it("renders a fallback column whose key is not a standard stage", () => {
    renderBoard({
      columns: [
        { key: "new", label: "جديد", cards: [makeCard(1)] },
        // A non-standard / removed-from-config status still gets a column.
        { key: "archived", label: "مؤرشف", cards: [makeCard(900, { title: "قديم" })] },
      ],
    });
    const fallback = screen.getByRole("region", { name: "مؤرشف" });
    expect(fallback).toBeInTheDocument();
    expect(within(fallback).getByText("قديم")).toBeInTheDocument();
  });
});

describe("Board card accessibility", () => {
  it("gives every card a keyboard-reachable drag handle (FR-034)", () => {
    renderBoard({
      columns: [
        {
          key: "new",
          label: "جديد",
          cards: [makeCard(1), makeCard(2)],
        },
      ],
    });
    const handles = screen.getAllByRole("button", {
      name: "اسحب لإعادة الترتيب",
    });
    expect(handles).toHaveLength(2);
  });

  // dnd-kit's KeyboardSensor coordinate math needs real layout (getBoundingClientRect
  // returns zeros in jsdom) and the live sensor context — both stubbed here — so an
  // actual keyboard-driven reorder cannot be exercised in this environment.
  it.skip("performs a full keyboard-driven reorder", () => {
    /* not feasible under jsdom without a real dnd sensor + layout. */
  });
});
