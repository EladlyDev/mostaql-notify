/// <reference types="vitest/globals" />
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import type { BoardCard, BoardResponse } from "@/lib/types";

// ---------------------------------------------------------------------------
// Capture the DndContext onDragEnd so the test can invoke a drag synthetically
// (no real pointer/keyboard simulation needed). dnd-kit primitives are stubbed
// so rendering doesn't depend on a live drag context.
// ---------------------------------------------------------------------------
const dnd = vi.hoisted(() => ({
  onDragEnd: undefined as undefined | ((event: unknown) => void),
}));

vi.mock("@dnd-kit/core", () => ({
  DndContext: ({
    onDragEnd,
    children,
  }: {
    onDragEnd: (event: unknown) => void;
    children: ReactNode;
  }) => {
    dnd.onDragEnd = onDragEnd;
    return children;
  },
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

// ---------------------------------------------------------------------------
// API mock: getBoard feeds useBoard's background query; moveBoardCard is the
// spy we assert against.
// ---------------------------------------------------------------------------
const { getBoardMock, moveBoardCardMock } = vi.hoisted(() => ({
  getBoardMock: vi.fn(),
  moveBoardCardMock: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  getBoard: getBoardMock,
  moveBoardCard: moveBoardCardMock,
}));

import { Board } from "@/components/board/Board";

function makeCard(project_id: number, title: string): BoardCard {
  return {
    project_id,
    title,
    url: null,
    client_hiring_rate: 80,
    budget_min: 100,
    budget_max: 200,
    currency: "USD",
    tier: 1,
    tier_label: "المستوى الأول",
    bids_count: 3,
    posted_at: "2026-06-27T10:00:00Z",
    tags: ["tag-a"],
    status: "new",
    board_position: 0,
  };
}

const mockBoard: BoardResponse = {
  columns: [
    { key: "new", label: "جديد", cards: [makeCard(101, "مشروع أ"), makeCard(102, "مشروع ب")] },
    { key: "applied", label: "تم التقديم", cards: [makeCard(201, "مشروع ج")] },
    { key: "won", label: "فاز", cards: [] },
  ],
};

function renderBoard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <Board board={mockBoard} />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  dnd.onDragEnd = undefined;
  getBoardMock.mockReset().mockResolvedValue(mockBoard);
  moveBoardCardMock.mockReset().mockResolvedValue(makeCard(101, "مشروع أ"));
});

describe("Board", () => {
  it("builds a column for each status, including an empty column as a present drop target", () => {
    renderBoard();

    expect(screen.getByRole("region", { name: "جديد" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "تم التقديم" })).toBeInTheDocument();
    // The empty "فاز" column is still rendered with its placeholder body so a
    // card can be dropped into it.
    const empty = screen.getByRole("region", { name: "فاز" });
    expect(empty).toBeInTheDocument();
    expect(screen.getByText("لا توجد مشاريع")).toBeInTheDocument();

    // Cards render too.
    expect(screen.getByText("مشروع أ")).toBeInTheDocument();
    expect(screen.getByText("مشروع ج")).toBeInTheDocument();
  });

  it("moves a card to another column (drop on the column body → append) via the move mutation", async () => {
    renderBoard();
    expect(dnd.onDragEnd).toBeTypeOf("function");

    // Drag card 101 (from "new") onto the "applied" column body.
    dnd.onDragEnd!({
      active: { id: 101 },
      over: { id: "column:applied" },
    });

    await waitFor(() => expect(moveBoardCardMock).toHaveBeenCalledTimes(1));
    // "applied" already holds one card (201) → appended at index 1.
    // (react-query passes a second context arg, so assert the body only.)
    expect(moveBoardCardMock.mock.calls[0][0]).toEqual({
      project_id: 101,
      to_status: "applied",
      position: 1,
    });
  });

  it("reorders by dropping onto another card (target index among the others)", async () => {
    renderBoard();
    expect(dnd.onDragEnd).toBeTypeOf("function");

    // Drag card 102 onto card 201 (in "applied"): target index 0 of that column.
    dnd.onDragEnd!({
      active: { id: 102 },
      over: { id: 201 },
    });

    await waitFor(() => expect(moveBoardCardMock).toHaveBeenCalledTimes(1));
    expect(moveBoardCardMock.mock.calls[0][0]).toEqual({
      project_id: 102,
      to_status: "applied",
      position: 0,
    });
  });
});
