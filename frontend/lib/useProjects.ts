"use client";

import { useCallback, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { getProjects } from "@/lib/api";
import type { ProjectListResponse } from "@/lib/types";

// ---------------------------------------------------------------------------
// Parsed filter / sort / paging state derived from the URL query string.
// ---------------------------------------------------------------------------

export type SortField = "posted_at" | "budget" | "bids_count" | "hiring_rate";
export type SortOrder = "asc" | "desc";
export type SiteStatus = "open" | "closed" | "unknown";

export interface ProjectFilters {
  tier?: 1 | 2;
  budget_min?: number;
  budget_max?: number;
  min_hiring_rate?: number;
  bids_min?: number;
  bids_max?: number;
  posted_within_hours?: number;
  site_status?: SiteStatus;
  qualified_only?: boolean;
  q?: string;
  // Feature 3 — personal filters.
  personal_status?: string;
  favorites_only?: boolean;
  include_hidden?: boolean;
}

export interface ProjectParams extends ProjectFilters {
  sort: SortField;
  order: SortOrder;
  page: number;
  page_size: number;
}

export const DEFAULT_SORT: SortField = "posted_at";
export const DEFAULT_ORDER: SortOrder = "desc";
export const DEFAULT_PAGE_SIZE = 25;

// Keys that are filters (changing any of them resets to page 1).
const FILTER_KEYS: (keyof ProjectFilters)[] = [
  "tier",
  "budget_min",
  "budget_max",
  "min_hiring_rate",
  "bids_min",
  "bids_max",
  "posted_within_hours",
  "site_status",
  "qualified_only",
  "q",
  "personal_status",
  "favorites_only",
  "include_hidden",
];

function num(raw: string | null): number | undefined {
  if (raw === null || raw.trim() === "") return undefined;
  const n = Number(raw);
  return Number.isFinite(n) ? n : undefined;
}

function parseParams(sp: URLSearchParams): ProjectParams {
  const tierRaw = num(sp.get("tier"));
  const tier = tierRaw === 1 || tierRaw === 2 ? (tierRaw as 1 | 2) : undefined;

  const siteRaw = sp.get("site_status");
  const site_status =
    siteRaw === "open" || siteRaw === "closed" || siteRaw === "unknown"
      ? siteRaw
      : undefined;

  const sortRaw = sp.get("sort");
  const sort: SortField =
    sortRaw === "budget" ||
    sortRaw === "bids_count" ||
    sortRaw === "hiring_rate" ||
    sortRaw === "posted_at"
      ? sortRaw
      : DEFAULT_SORT;

  const orderRaw = sp.get("order");
  const order: SortOrder = orderRaw === "asc" ? "asc" : DEFAULT_ORDER;

  const pageRaw = num(sp.get("page"));
  const page = pageRaw && pageRaw >= 1 ? Math.floor(pageRaw) : 1;

  const pageSizeRaw = num(sp.get("page_size"));
  const page_size =
    pageSizeRaw && pageSizeRaw >= 1 && pageSizeRaw <= 100
      ? Math.floor(pageSizeRaw)
      : DEFAULT_PAGE_SIZE;

  const q = sp.get("q") ?? undefined;

  return {
    tier,
    budget_min: num(sp.get("budget_min")),
    budget_max: num(sp.get("budget_max")),
    min_hiring_rate: num(sp.get("min_hiring_rate")),
    bids_min: num(sp.get("bids_min")),
    bids_max: num(sp.get("bids_max")),
    posted_within_hours: num(sp.get("posted_within_hours")),
    site_status,
    qualified_only: sp.get("qualified_only") === "true" ? true : undefined,
    q: q && q.trim() !== "" ? q : undefined,
    personal_status: sp.get("personal_status") ?? undefined,
    favorites_only: sp.get("favorites_only") === "true" ? true : undefined,
    include_hidden: sp.get("include_hidden") === "true" ? true : undefined,
    sort,
    order,
    page,
    page_size,
  };
}

/** Drop defaults / empty values so they never appear in the request or URL. */
function toQueryParams(
  p: ProjectParams
): Record<string, string | number | boolean | undefined> {
  return {
    tier: p.tier,
    budget_min: p.budget_min,
    budget_max: p.budget_max,
    min_hiring_rate: p.min_hiring_rate,
    bids_min: p.bids_min,
    bids_max: p.bids_max,
    posted_within_hours: p.posted_within_hours,
    site_status: p.site_status,
    qualified_only: p.qualified_only ? true : undefined,
    q: p.q,
    personal_status: p.personal_status,
    favorites_only: p.favorites_only ? true : undefined,
    include_hidden: p.include_hidden ? true : undefined,
    sort: p.sort === DEFAULT_SORT ? undefined : p.sort,
    order: p.order === DEFAULT_ORDER ? undefined : p.order,
    page: p.page > 1 ? p.page : undefined,
    page_size: p.page_size === DEFAULT_PAGE_SIZE ? undefined : p.page_size,
  };
}

/** True when any user-facing filter (or search) is active. */
export function hasActiveFilters(p: ProjectParams): boolean {
  return FILTER_KEYS.some((k) => p[k] !== undefined);
}

export interface UseProjectsResult {
  params: ProjectParams;
  /** Reactive flag: are any filters / search active? */
  filtersActive: boolean;
  data: ProjectListResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => void;
  /** Patch one or more filters; resets to page 1. */
  setFilters: (patch: Partial<ProjectFilters>) => void;
  setSort: (sort: SortField, order?: SortOrder) => void;
  setPage: (page: number) => void;
  clearFilters: () => void;
}

export function useProjects(): UseProjectsResult {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // Stable string key so memoization / queryKey only change on real changes.
  const spString = searchParams.toString();

  const params = useMemo(
    () => parseParams(new URLSearchParams(spString)),
    [spString]
  );

  const queryParams = useMemo(() => toQueryParams(params), [params]);

  const query = useQuery({
    queryKey: ["projects", queryParams],
    queryFn: () => getProjects(queryParams),
    placeholderData: (prev) => prev,
  });

  // Build a URL from a full set of params and navigate to it.
  const pushParams = useCallback(
    (next: ProjectParams) => {
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

  const setFilters = useCallback(
    (patch: Partial<ProjectFilters>) => {
      // Changing a filter always resets paging.
      pushParams({ ...params, ...patch, page: 1 });
    },
    [params, pushParams]
  );

  const setSort = useCallback(
    (sort: SortField, order?: SortOrder) => {
      pushParams({
        ...params,
        sort,
        order: order ?? params.order,
        page: 1,
      });
    },
    [params, pushParams]
  );

  const setPage = useCallback(
    (page: number) => {
      pushParams({ ...params, page: Math.max(1, Math.floor(page)) });
    },
    [params, pushParams]
  );

  const clearFilters = useCallback(() => {
    // Preserve sort / order / page_size; drop every filter and reset page.
    pushParams({
      sort: params.sort,
      order: params.order,
      page: 1,
      page_size: params.page_size,
    });
  }, [params, pushParams]);

  return {
    params,
    filtersActive: hasActiveFilters(params),
    data: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    refetch: query.refetch,
    setFilters,
    setSort,
    setPage,
    clearFilters,
  };
}
