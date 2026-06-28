"use client";

import { useQuery } from "@tanstack/react-query";

import { getStatuses } from "@/lib/api";
import type { PersonalStatusOption } from "@/lib/types";

// The configured pipeline stages (slug + Arabic label). Cached aggressively — the set rarely
// changes (it's a config setting), and the feed/detail status pickers all read it.
export function useStatuses() {
  return useQuery<PersonalStatusOption[]>({
    queryKey: ["statuses"],
    queryFn: getStatuses,
    staleTime: 5 * 60 * 1000,
  });
}
