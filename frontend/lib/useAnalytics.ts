"use client";

import { useCallback, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { getAnalyticsOverview } from "@/lib/api";
import type { AnalyticsOverview } from "@/lib/types";

// ---------------------------------------------------------------------------
// Analytics date-range state, held in the URL (?date_from=&date_to=) so the
// whole section is shareable/back-button friendly — the `useProjects` idiom.
// Both bounds are calendar dates (YYYY-MM-DD) in the configured analytics tz.
// ---------------------------------------------------------------------------

export const RANGE_PRESETS = [7, 30, 90] as const;
export type RangePreset = (typeof RANGE_PRESETS)[number];

export interface AnalyticsParams {
  date_from?: string;
  date_to?: string;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function isoDate(raw: string | null): string | undefined {
  return raw && ISO_DATE.test(raw) ? raw : undefined;
}

function parseParams(sp: URLSearchParams): AnalyticsParams {
  return {
    date_from: isoDate(sp.get("date_from")),
    date_to: isoDate(sp.get("date_to")),
  };
}

function toQueryParams(
  p: AnalyticsParams
): Record<string, string | undefined> {
  return { date_from: p.date_from, date_to: p.date_to };
}

export interface UseAnalyticsResult {
  params: AnalyticsParams;
  data: AnalyticsOverview | undefined;
  isLoading: boolean;
  isFetching: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => void;
  /** Replace the range (either bound omitted ⇒ server default for that bound). */
  setRange: (next: AnalyticsParams) => void;
}

export function useAnalytics(): UseAnalyticsResult {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const spString = searchParams.toString();
  const params = useMemo(
    () => parseParams(new URLSearchParams(spString)),
    [spString]
  );
  const queryParams = useMemo(() => toQueryParams(params), [params]);

  const query = useQuery({
    queryKey: ["analytics", queryParams],
    queryFn: () => getAnalyticsOverview(queryParams),
    placeholderData: (prev) => prev,
  });

  const setRange = useCallback(
    (next: AnalyticsParams) => {
      const qp = toQueryParams(next);
      const search = new URLSearchParams();
      for (const [key, value] of Object.entries(qp)) {
        if (value === undefined || value === null || value === "") continue;
        search.set(key, String(value));
      }
      const qs = search.toString();
      router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname]
  );

  return {
    params,
    data: query.data,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    isError: query.isError,
    error: query.error,
    refetch: query.refetch,
    setRange,
  };
}
