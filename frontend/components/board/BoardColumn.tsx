"use client";

import { useDroppable } from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";

import type { BoardColumn as BoardColumnData } from "@/lib/types";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Bidi } from "@/components/Bidi";
import { BoardCard } from "@/components/board/BoardCard";

// Stable droppable id for a column. Prefixed so it never collides with a
// numeric card id; `resolveMove` strips the prefix back to the status key.
export const COLUMN_ID_PREFIX = "column:";

export function columnDroppableId(key: string): string {
  return `${COLUMN_ID_PREFIX}${key}`;
}

/**
 * A status column: a droppable region with a header (label + count) and a
 * sortable list of its cards. An empty column still renders its droppable body
 * (with a placeholder) so a card can be dropped into it.
 */
export function BoardColumn({ column }: { column: BoardColumnData }) {
  const { setNodeRef, isOver } = useDroppable({
    id: columnDroppableId(column.key),
  });

  return (
    <section
      className="flex w-72 shrink-0 flex-col rounded-xl bg-muted/40 ring-1 ring-foreground/5"
      aria-label={column.label}
    >
      <header className="flex items-center justify-between gap-2 px-3 py-2.5">
        <h2 className="text-sm font-semibold">
          <Bidi>{column.label}</Bidi>
        </h2>
        <span className="rounded-full bg-background px-2 py-0.5 text-xs text-muted-foreground tabular-nums">
          <Bidi>{formatNumber(column.cards.length)}</Bidi>
        </span>
      </header>

      <SortableContext
        items={column.cards.map((c) => c.project_id)}
        strategy={verticalListSortingStrategy}
      >
        <div
          ref={setNodeRef}
          className={cn(
            "flex min-h-24 flex-1 flex-col gap-2 rounded-b-xl px-2 pb-2 transition-colors",
            isOver && "bg-primary/5 ring-1 ring-inset ring-primary/30"
          )}
        >
          {column.cards.length === 0 ? (
            <p className="flex flex-1 items-center justify-center rounded-lg border border-dashed py-6 text-center text-xs text-muted-foreground">
              لا توجد مشاريع
            </p>
          ) : (
            column.cards.map((card) => (
              <BoardCard key={card.project_id} card={card} />
            ))
          )}
        </div>
      </SortableContext>
    </section>
  );
}
