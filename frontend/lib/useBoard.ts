"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { getBoard, moveBoardCard } from "@/lib/api";
import type { BoardCard, BoardMoveRequest, BoardResponse } from "@/lib/types";

// Single source of truth for the board query key so the mutation can both
// optimistically patch and invalidate it.
export const BOARD_KEY = ["board"] as const;

/** The pipeline board (engaged, non-hidden projects grouped by status). */
export function useBoard(): UseQueryResult<BoardResponse> {
  return useQuery({ queryKey: BOARD_KEY, queryFn: getBoard });
}

/**
 * Pure helper: return a new {@link BoardResponse} with `project_id` removed
 * from whatever column currently holds it and re-inserted into the
 * `to_status` column at `position`. Used for the optimistic cache update so a
 * drag feels instant before the server confirms.
 */
export function applyMoveToBoard(
  board: BoardResponse,
  req: BoardMoveRequest
): BoardResponse {
  let moved: BoardCard | undefined;

  // Strip the card out of every column (it can only live in one).
  const stripped = board.columns.map((col) => {
    const found = col.cards.find((c) => c.project_id === req.project_id);
    if (!found) return col;
    moved = found;
    return {
      ...col,
      cards: col.cards.filter((c) => c.project_id !== req.project_id),
    };
  });

  if (!moved) return board;
  const updated: BoardCard = { ...moved, status: req.to_status };

  // Re-insert into the destination column at the requested index. If the
  // target column no longer exists (e.g. fallback key), the settle-time
  // invalidation reconciles it.
  const columns = stripped.map((col) => {
    if (col.key !== req.to_status) return col;
    const cards = [...col.cards];
    const at = Math.max(0, Math.min(req.position, cards.length));
    cards.splice(at, 0, updated);
    return { ...col, cards };
  });

  return { columns };
}

/**
 * Move/reorder a card. Optimistically rewrites the `["board"]` cache, rolls
 * back on error, and invalidates the board + project feed on settle so the
 * derived personal_status everywhere stays in sync.
 */
export function useMoveCard(): UseMutationResult<
  BoardCard,
  unknown,
  BoardMoveRequest,
  { previous?: BoardResponse }
> {
  const qc = useQueryClient();

  return useMutation({
    mutationFn: moveBoardCard,
    onMutate: async (req) => {
      await qc.cancelQueries({ queryKey: BOARD_KEY });
      const previous = qc.getQueryData<BoardResponse>(BOARD_KEY);
      if (previous) {
        qc.setQueryData<BoardResponse>(BOARD_KEY, applyMoveToBoard(previous, req));
      }
      return { previous };
    },
    onError: (_err, _req, ctx) => {
      if (ctx?.previous) qc.setQueryData(BOARD_KEY, ctx.previous);
    },
    onSettled: (_data, _err, req) => {
      qc.invalidateQueries({ queryKey: BOARD_KEY });
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["project", req.project_id] });
    },
  });
}
