"use client";

import { useQuery } from "@tanstack/react-query";

import { getUploadConfig } from "@/lib/api";
import type { UploadConfig } from "@/lib/types";

// Config-driven upload limits (allowed types + max size) for the dropzone hint. Rarely changes.
export function useUploadConfig() {
  return useQuery<UploadConfig>({
    queryKey: ["upload-config"],
    queryFn: getUploadConfig,
    staleTime: 5 * 60 * 1000,
  });
}
