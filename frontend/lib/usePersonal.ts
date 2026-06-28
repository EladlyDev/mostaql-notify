"use client";

import { useCallback } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";

import { getPersonal, toggleFavorite, updatePersonal } from "@/lib/api";
import type { PersonalRecord, PersonalUpdate } from "@/lib/types";

// ---------------------------------------------------------------------------
// Query keys — keep in sync with the rest of the app (mirrors useProjects.ts).
//   feed   → ["projects", …params]   (prefix-invalidated)
//   detail → ["project", projectId]
//   board  → ["board"]
//   record → ["personal", projectId]
// ---------------------------------------------------------------------------

export const personalKeys = {
  /** A single project's personal CRM record. */
  record: (projectId: number) => ["personal", projectId] as const,
};

/**
 * Invalidate every cache a personal mutation can touch so the feed row, the
 * project detail/workspace, the Kanban board, and the standalone record query
 * all refetch their projected `favorite` / `status` / `tags` / `hidden` fields.
 */
function invalidatePersonal(qc: QueryClient, projectId: number): void {
  // Feed: ["projects", params] — prefix match invalidates every page/filter.
  qc.invalidateQueries({ queryKey: ["projects"] });
  // Detail / workspace view.
  qc.invalidateQueries({ queryKey: ["project", projectId] });
  // Kanban board.
  qc.invalidateQueries({ queryKey: ["board"] });
  // Standalone personal record.
  qc.invalidateQueries({ queryKey: personalKeys.record(projectId) });
}

/** Shared success-invalidation callback factory used by every mutation. */
function useInvalidatePersonal(): (projectId: number) => void {
  const qc = useQueryClient();
  return useCallback((projectId: number) => invalidatePersonal(qc, projectId), [qc]);
}

// ---------------------------------------------------------------------------
// Query — the full personal record for one project.
// ---------------------------------------------------------------------------

export function usePersonalRecord(projectId: number, enabled = true) {
  return useQuery({
    queryKey: personalKeys.record(projectId),
    queryFn: () => getPersonal(projectId),
    enabled,
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export interface UpdatePersonalVars {
  projectId: number;
  patch: PersonalUpdate;
}

/** General-purpose patch of any subset of the personal record. */
export function useUpdatePersonal() {
  const invalidate = useInvalidatePersonal();
  return useMutation<PersonalRecord, unknown, UpdatePersonalVars>({
    mutationFn: ({ projectId, patch }) => updatePersonal(projectId, patch),
    onSuccess: (_data, { projectId }) => invalidate(projectId),
  });
}

/** Toggle the favorite (star) flag via the dedicated endpoint. */
export function useToggleFavorite() {
  const invalidate = useInvalidatePersonal();
  return useMutation<PersonalRecord, unknown, number>({
    mutationFn: (projectId) => toggleFavorite(projectId),
    onSuccess: (_data, projectId) => invalidate(projectId),
  });
}

export interface SetStatusVars {
  projectId: number;
  status: string;
}

/** Move a project to a configured pipeline stage. */
export function useSetStatus() {
  const invalidate = useInvalidatePersonal();
  return useMutation<PersonalRecord, unknown, SetStatusVars>({
    mutationFn: ({ projectId, status }) => updatePersonal(projectId, { status }),
    onSuccess: (_data, { projectId }) => invalidate(projectId),
  });
}

export interface SetTagsVars {
  projectId: number;
  tags: string[];
}

/** Replace the free-form tag set. */
export function useSetTags() {
  const invalidate = useInvalidatePersonal();
  return useMutation<PersonalRecord, unknown, SetTagsVars>({
    mutationFn: ({ projectId, tags }) => updatePersonal(projectId, { tags }),
    onSuccess: (_data, { projectId }) => invalidate(projectId),
  });
}

export interface SetOutcomeVars {
  projectId: number;
  wonAmount?: number | null;
  lostReason?: string | null;
}

/** Record the won amount and/or the lost reason for a terminal status. */
export function useSetOutcome() {
  const invalidate = useInvalidatePersonal();
  return useMutation<PersonalRecord, unknown, SetOutcomeVars>({
    mutationFn: ({ projectId, wonAmount, lostReason }) => {
      const patch: PersonalUpdate = {};
      if (wonAmount !== undefined) patch.won_amount = wonAmount;
      if (lostReason !== undefined) patch.lost_reason = lostReason;
      return updatePersonal(projectId, patch);
    },
    onSuccess: (_data, { projectId }) => invalidate(projectId),
  });
}

/** Hide a project from the active feed/board. */
export function useHide() {
  const invalidate = useInvalidatePersonal();
  return useMutation<PersonalRecord, unknown, number>({
    mutationFn: (projectId) => updatePersonal(projectId, { hidden: true }),
    onSuccess: (_data, projectId) => invalidate(projectId),
  });
}

/** Restore a previously hidden project. */
export function useUnhide() {
  const invalidate = useInvalidatePersonal();
  return useMutation<PersonalRecord, unknown, number>({
    mutationFn: (projectId) => updatePersonal(projectId, { hidden: false }),
    onSuccess: (_data, projectId) => invalidate(projectId),
  });
}
