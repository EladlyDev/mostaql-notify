/// <reference types="vitest/globals" />
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { ControlState } from "@/lib/types";

// ---------------------------------------------------------------------------
// PauseControl reads useControl() and fires usePause()/useResume(), all of which
// call the API module. Mock it so the watcher endpoints are spies.
// ---------------------------------------------------------------------------
const { getControlSpy, pauseWatcherSpy, resumeWatcherSpy } = vi.hoisted(() => ({
  getControlSpy: vi.fn(),
  pauseWatcherSpy: vi.fn(),
  resumeWatcherSpy: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  getControl: getControlSpy,
  pauseWatcher: pauseWatcherSpy,
  resumeWatcher: resumeWatcherSpy,
}));

import { PauseControl } from "@/components/PauseControl";

beforeAll(() => {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver =
    ResizeObserverStub as unknown as typeof ResizeObserver;

  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });

  Element.prototype.scrollIntoView = () => {};
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
});

function renderControl() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <PauseControl />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  pauseWatcherSpy.mockResolvedValue({ paused: true } as ControlState);
  resumeWatcherSpy.mockResolvedValue({ paused: false } as ControlState);
});

describe("PauseControl", () => {
  it("reflects the running state (switch on, 'نشط')", async () => {
    getControlSpy.mockResolvedValue({ paused: false } as ControlState);
    renderControl();
    await waitFor(() => expect(screen.getByText("نشط")).toBeInTheDocument());
    const sw = screen.getByRole("switch");
    expect(sw).toHaveAttribute("aria-checked", "true");
  });

  it("reflects the paused state (switch off, 'متوقّف')", async () => {
    getControlSpy.mockResolvedValue({ paused: true } as ControlState);
    renderControl();
    await waitFor(() =>
      expect(screen.getByText("متوقّف")).toBeInTheDocument()
    );
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
  });

  it("pauses the watcher when toggled off while running", async () => {
    getControlSpy.mockResolvedValue({ paused: false } as ControlState);
    renderControl();
    const sw = await screen.findByRole("switch");
    await waitFor(() => expect(sw).not.toBeDisabled());
    fireEvent.click(sw);
    await waitFor(() => expect(pauseWatcherSpy).toHaveBeenCalledTimes(1));
    expect(resumeWatcherSpy).not.toHaveBeenCalled();
  });

  it("resumes the watcher when toggled on while paused", async () => {
    getControlSpy.mockResolvedValue({ paused: true } as ControlState);
    renderControl();
    const sw = await screen.findByRole("switch");
    await waitFor(() => expect(sw).not.toBeDisabled());
    fireEvent.click(sw);
    await waitFor(() => expect(resumeWatcherSpy).toHaveBeenCalledTimes(1));
    expect(pauseWatcherSpy).not.toHaveBeenCalled();
  });

  it("shows 'غير متاح' and disables the switch when control is unavailable", async () => {
    getControlSpy.mockRejectedValue(new Error("boom"));
    renderControl();
    await waitFor(() =>
      expect(screen.getByText("غير متاح")).toBeInTheDocument()
    );
    // Base UI's Switch renders a <span role="switch"> and signals the disabled
    // state via aria-disabled (not the native disabled attribute).
    expect(screen.getByRole("switch")).toHaveAttribute("aria-disabled", "true");
  });
});
