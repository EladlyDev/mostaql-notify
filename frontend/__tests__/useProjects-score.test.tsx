/// <reference types="vitest/globals" />
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const { getProjectsSpy, pushSpy, state } = vi.hoisted(() => ({
  getProjectsSpy: vi.fn(),
  pushSpy: vi.fn(),
  state: { search: "" },
}));

vi.mock("@/lib/api", () => ({ getProjects: getProjectsSpy }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushSpy }),
  usePathname: () => "/projects",
  useSearchParams: () => new URLSearchParams(state.search),
}));

import { useProjects } from "@/lib/useProjects";

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return wrapper;
}

function lastQueryParams(): Record<string, unknown> {
  const calls = getProjectsSpy.mock.calls;
  return (calls[calls.length - 1]?.[0] ?? {}) as Record<string, unknown>;
}

beforeEach(() => {
  vi.clearAllMocks();
  state.search = "";
  getProjectsSpy.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 25 });
});

describe("useProjects — Feature 4 score sort", () => {
  it("parses sort=score from the URL and forwards it to getProjects", async () => {
    state.search = "sort=score";
    const { result } = renderHook(() => useProjects(), { wrapper: makeWrapper() });

    expect(result.current.params.sort).toBe("score");
    await waitFor(() => expect(getProjectsSpy).toHaveBeenCalled());
    expect(lastQueryParams().sort).toBe("score");
  });

  it("omits sort from the request when it is the default (posted_at)", async () => {
    state.search = "";
    renderHook(() => useProjects(), { wrapper: makeWrapper() });
    await waitFor(() => expect(getProjectsSpy).toHaveBeenCalled());
    expect(lastQueryParams().sort).toBeUndefined();
  });

  it("setSort('score') pushes a URL carrying sort=score", () => {
    const { result } = renderHook(() => useProjects(), { wrapper: makeWrapper() });
    act(() => result.current.setSort("score"));
    expect(pushSpy).toHaveBeenCalledWith(
      expect.stringContaining("sort=score"),
      { scroll: false }
    );
  });
});

describe("useProjects — Feature 4 score_min / score_max", () => {
  it("parses and forwards score_min / score_max within 0–100", async () => {
    state.search = "score_min=40&score_max=90";
    const { result } = renderHook(() => useProjects(), { wrapper: makeWrapper() });

    expect(result.current.params.score_min).toBe(40);
    expect(result.current.params.score_max).toBe(90);
    await waitFor(() => expect(getProjectsSpy).toHaveBeenCalled());
    const qp = lastQueryParams();
    expect(qp.score_min).toBe(40);
    expect(qp.score_max).toBe(90);
  });

  it("clamps out-of-range score bounds into 0–100", () => {
    state.search = "score_min=-20&score_max=250";
    const { result } = renderHook(() => useProjects(), { wrapper: makeWrapper() });
    expect(result.current.params.score_min).toBe(0);
    expect(result.current.params.score_max).toBe(100);
  });

  it("ignores a non-numeric score bound (undefined)", () => {
    state.search = "score_min=abc";
    const { result } = renderHook(() => useProjects(), { wrapper: makeWrapper() });
    expect(result.current.params.score_min).toBeUndefined();
  });

  it("leaves score bounds undefined when absent and marks no active filters", async () => {
    state.search = "";
    const { result } = renderHook(() => useProjects(), { wrapper: makeWrapper() });
    expect(result.current.params.score_min).toBeUndefined();
    expect(result.current.params.score_max).toBeUndefined();
    expect(result.current.filtersActive).toBe(false);
    await waitFor(() => expect(getProjectsSpy).toHaveBeenCalled());
    expect(lastQueryParams().score_min).toBeUndefined();
    expect(lastQueryParams().score_max).toBeUndefined();
  });

  it("treats a present score bound as an active filter", () => {
    state.search = "score_min=50";
    const { result } = renderHook(() => useProjects(), { wrapper: makeWrapper() });
    expect(result.current.filtersActive).toBe(true);
  });

  it("setFilters({ score_min, score_max }) pushes a URL carrying both bounds and resets to page 1", () => {
    state.search = "page=3";
    const { result } = renderHook(() => useProjects(), { wrapper: makeWrapper() });
    act(() => result.current.setFilters({ score_min: 70, score_max: 95 }));
    const url = pushSpy.mock.calls[0][0] as string;
    expect(url).toContain("score_min=70");
    expect(url).toContain("score_max=95");
    expect(url).not.toContain("page=");
  });

  it("includes the score bounds in the TanStack query key (refetch on change)", async () => {
    state.search = "score_min=10";
    renderHook(() => useProjects(), { wrapper: makeWrapper() });
    await waitFor(() => expect(getProjectsSpy).toHaveBeenCalled());
    // queryFn receives the same toQueryParams object used as the key tail.
    expect(lastQueryParams().score_min).toBe(10);
  });
});
