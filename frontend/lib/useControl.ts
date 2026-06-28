"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { getControl, pauseWatcher, resumeWatcher } from "@/lib/api";
import type { ControlState } from "@/lib/types";

export const CONTROL_KEY = ["control"] as const;
const HOME_KEY = ["home"] as const;

/** The watcher's pause state (mirrors the Telegram /pause·/resume flag). */
export function useControl(): UseQueryResult<ControlState> {
  return useQuery({ queryKey: CONTROL_KEY, queryFn: getControl });
}

// Shared optimistic mutation: flips `paused` immediately, rolls back on error,
// and invalidates control + home (the dashboard surfaces the same flag).
function useControlMutation(
  mutationFn: () => Promise<ControlState>,
  nextPaused: boolean
): UseMutationResult<ControlState, unknown, void, { previous?: ControlState }> {
  const qc = useQueryClient();

  return useMutation({
    mutationFn,
    onMutate: async () => {
      await qc.cancelQueries({ queryKey: CONTROL_KEY });
      const previous = qc.getQueryData<ControlState>(CONTROL_KEY);
      qc.setQueryData<ControlState>(CONTROL_KEY, { paused: nextPaused });
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous !== undefined) {
        qc.setQueryData(CONTROL_KEY, ctx.previous);
      }
    },
    onSuccess: (data) => {
      qc.setQueryData(CONTROL_KEY, data);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: CONTROL_KEY });
      qc.invalidateQueries({ queryKey: HOME_KEY });
    },
  });
}

/** Pause the watcher (sets `watcher_paused = true`). Idempotent. */
export function usePause() {
  return useControlMutation(pauseWatcher, true);
}

/** Resume the watcher (sets `watcher_paused = false`). Idempotent. */
export function useResume() {
  return useControlMutation(resumeWatcher, false);
}
