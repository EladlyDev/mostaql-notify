"use client";

import { useCallback } from "react";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCorners,
  useSensor,
  useSensors,
  type DragEndEvent,
  type UniqueIdentifier,
} from "@dnd-kit/core";
import { sortableKeyboardCoordinates } from "@dnd-kit/sortable";

import type {
  BoardColumn as BoardColumnData,
  BoardMoveRequest,
  BoardResponse,
} from "@/lib/types";
import { useBoard, useMoveCard } from "@/lib/useBoard";
import { Loading } from "@/components/states/Loading";
import { ErrorState } from "@/components/states/ErrorState";
import { EmptyState } from "@/components/states/EmptyState";
import { BoardColumn, COLUMN_ID_PREFIX } from "@/components/board/BoardColumn";

/**
 * Pure mapping from a dnd-kit drag-end (active card + drop target) to a
 * {@link BoardMoveRequest}.
 *
 * - `to_status` is the destination column's key: taken directly from a column
 *   drop target, or inferred from the column that holds the card being dropped on.
 * - `position` is the target index **among the other cards** of that column
 *   (the active card removed). Dropping on the column body appends; the server
 *   normalizes this index into a `board_position`.
 *
 * Returns `null` for a no-op (no target, or dropped on itself).
 */
export function resolveMove(
  columns: BoardColumnData[],
  activeId: UniqueIdentifier,
  overId: UniqueIdentifier | null
): BoardMoveRequest | null {
  if (overId == null || overId === activeId) return null;

  const projectId = Number(activeId);
  if (!Number.isFinite(projectId)) return null;

  let toStatus: string | null = null;
  let overCardId: number | null = null;

  if (typeof overId === "string" && overId.startsWith(COLUMN_ID_PREFIX)) {
    toStatus = overId.slice(COLUMN_ID_PREFIX.length);
  } else {
    overCardId = Number(overId);
    const owner = columns.find((c) =>
      c.cards.some((card) => card.project_id === overCardId)
    );
    if (!owner) return null;
    toStatus = owner.key;
  }

  const target = columns.find((c) => c.key === toStatus);
  if (!target) return null;

  const others = target.cards.filter((c) => c.project_id !== projectId);
  let position: number;
  if (overCardId == null) {
    position = others.length; // dropped on the column body → append
  } else {
    const idx = others.findIndex((c) => c.project_id === overCardId);
    position = idx === -1 ? others.length : idx;
  }

  return { project_id: projectId, to_status: toStatus, position };
}

/**
 * The Kanban board. Renders columns in configured order and wires drag-end to
 * the move mutation. Accepts an explicit `board` (e.g. from a page that already
 * fetched it) or falls back to its own `useBoard()` query, handling loading,
 * error, and the no-engaged-projects empty state.
 */
export function Board({ board }: { board?: BoardResponse }) {
  const query = useBoard();
  const move = useMoveCard();

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const data = board ?? query.data;

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      if (!data) return;
      const req = resolveMove(
        data.columns,
        event.active.id,
        event.over?.id ?? null
      );
      if (req) move.mutate(req);
    },
    [data, move]
  );

  if (!data) {
    if (!board && query.isError) {
      return <ErrorState onRetry={() => query.refetch()} />;
    }
    return <Loading rows={4} />;
  }

  const totalCards = data.columns.reduce((n, c) => n + c.cards.length, 0);
  if (totalCards === 0) {
    return (
      <EmptyState
        title="لا توجد مشاريع في خط الأنابيب"
        message="عندما تضيف مشروعًا إلى المفضلة أو تغيّر حالته، سيظهر هنا على اللوحة."
      />
    );
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragEnd={handleDragEnd}
    >
      <div className="flex items-start gap-3 overflow-x-auto pb-4">
        {data.columns.map((column) => (
          <BoardColumn key={column.key} column={column} />
        ))}
      </div>
    </DndContext>
  );
}
