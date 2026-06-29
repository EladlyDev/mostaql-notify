/// <reference types="vitest/globals" />
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

import type { Lifecycle } from "@/lib/types";

const { getLifecycleSpy } = vi.hoisted(() => ({ getLifecycleSpy: vi.fn() }));

vi.mock("@/lib/api", () => ({ getLifecycle: getLifecycleSpy }));

import { useLifecycle, lifecycleKeys } from "@/lib/useLifecycle";

const LIFECYCLE: Lifecycle = {
  outcome: "open",
  snapshots: [],
  status_timeline: [],
};

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("lifecycleKeys", () => {
  it("namespaces per project id", () => {
    expect(lifecycleKeys.detail(42)).toEqual(["lifecycle", 42]);
    expect(lifecycleKeys.detail("abc")).toEqual(["lifecycle", "abc"]);
  });
});

describe("useLifecycle", () => {
  it("starts in a loading state then resolves to the lifecycle, calling getLifecycle with the id", async () => {
    getLifecycleSpy.mockResolvedValue(LIFECYCLE);
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useLifecycle(7), { wrapper });

    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(LIFECYCLE);
    expect(getLifecycleSpy).toHaveBeenCalledWith(7);
  });

  it("surfaces an error state when the request fails", async () => {
    getLifecycleSpy.mockRejectedValue(new Error("boom"));
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useLifecycle(9), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });

  it("does not fetch when enabled=false", () => {
    getLifecycleSpy.mockResolvedValue(LIFECYCLE);
    const { wrapper } = makeWrapper();
    const { result } = renderHook(() => useLifecycle(7, false), { wrapper });

    expect(getLifecycleSpy).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("shares the cache across hooks with the same id (one fetch)", async () => {
    getLifecycleSpy.mockResolvedValue(LIFECYCLE);
    const { wrapper } = makeWrapper();

    const a = renderHook(() => useLifecycle(7), { wrapper });
    const b = renderHook(() => useLifecycle(7), { wrapper });

    await waitFor(() => expect(a.result.current.isSuccess).toBe(true));
    await waitFor(() => expect(b.result.current.isSuccess).toBe(true));
    expect(getLifecycleSpy).toHaveBeenCalledTimes(1);
  });

  it("fetches separately for distinct ids", async () => {
    getLifecycleSpy.mockResolvedValue(LIFECYCLE);
    const { wrapper } = makeWrapper();

    renderHook(() => useLifecycle(1), { wrapper });
    renderHook(() => useLifecycle(2), { wrapper });

    await waitFor(() => expect(getLifecycleSpy).toHaveBeenCalledTimes(2));
    expect(getLifecycleSpy).toHaveBeenCalledWith(1);
    expect(getLifecycleSpy).toHaveBeenCalledWith(2);
  });
});
