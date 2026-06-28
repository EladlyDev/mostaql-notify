"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  ApiError,
  deleteAttachment,
  listAttachments,
  renameAttachment,
  uploadAttachment,
} from "@/lib/api";
import type { AttachmentItem, AttachmentListResponse } from "@/lib/types";

// Single source of truth for the attachments cache key so the query and every
// mutation invalidate exactly the same entry (mirrors the useProjects pattern).
export function attachmentsKey(projectId: number): readonly [string, number] {
  return ["attachments", projectId] as const;
}

/** Query the attachment list for a project. */
export function useAttachments(
  projectId: number
): UseQueryResult<AttachmentListResponse, ApiError> {
  return useQuery<AttachmentListResponse, ApiError>({
    queryKey: attachmentsKey(projectId),
    queryFn: () => listAttachments(projectId),
  });
}

/**
 * Upload a single file. On reject the error is an {@link ApiError} whose
 * `.message` is the server `detail` (400 = wrong type, 413 = too large) — the
 * UI surfaces `mutation.error?.message` to the user.
 */
export function useUploadAttachment(
  projectId: number
): UseMutationResult<AttachmentItem, ApiError, File> {
  const queryClient = useQueryClient();
  return useMutation<AttachmentItem, ApiError, File>({
    mutationFn: (file: File) => uploadAttachment(projectId, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: attachmentsKey(projectId) });
    },
  });
}

export interface RenameAttachmentVars {
  attachmentId: number;
  originalName: string;
}

/** Rename an attachment's display (original) name. */
export function useRenameAttachment(
  projectId: number
): UseMutationResult<AttachmentItem, ApiError, RenameAttachmentVars> {
  const queryClient = useQueryClient();
  return useMutation<AttachmentItem, ApiError, RenameAttachmentVars>({
    mutationFn: ({ attachmentId, originalName }) =>
      renameAttachment(attachmentId, originalName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: attachmentsKey(projectId) });
    },
  });
}

/** Delete an attachment by id. */
export function useDeleteAttachment(
  projectId: number
): UseMutationResult<null, ApiError, number> {
  const queryClient = useQueryClient();
  return useMutation<null, ApiError, number>({
    mutationFn: (attachmentId: number) => deleteAttachment(attachmentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: attachmentsKey(projectId) });
    },
  });
}
