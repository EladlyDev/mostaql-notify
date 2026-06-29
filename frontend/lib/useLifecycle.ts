"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { getLifecycle } from "@/lib/api";
import type { Lifecycle } from "@/lib/types";

// Query key — kept alongside the rest of the app's keys (mirrors useControl /
// usePersonal). The detail page's lifecycle card reads this.
export const lifecycleKeys = {
  detail: (projectId: number | string) => ["lifecycle", projectId] as const,
};

/**
 * The project's append-only lifecycle: bid/status trajectory, deduped status
 * timeline, and final outcome (GET /api/projects/{id}/lifecycle).
 */
export function useLifecycle(
  projectId: number | string,
  enabled = true
): UseQueryResult<Lifecycle> {
  return useQuery({
    queryKey: lifecycleKeys.detail(projectId),
    queryFn: () => getLifecycle(projectId),
    enabled: enabled && projectId !== undefined && projectId !== null,
  });
}
