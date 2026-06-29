/// <reference types="vitest/globals" />
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { SettingItem, SettingsResponse } from "@/lib/types";

// ---------------------------------------------------------------------------
// Mock the settings API so the save mutation is an assertable spy.
// ---------------------------------------------------------------------------
const { updateSettingsSpy } = vi.hoisted(() => ({ updateSettingsSpy: vi.fn() }));

vi.mock("@/lib/api", () => ({
  updateSettings: updateSettingsSpy,
  // The form references ApiError for instanceof checks in its error handler.
  ApiError: class ApiError extends Error {
    status: number;
    body: unknown;
    constructor(status: number, message: string, body?: unknown) {
      super(message);
      this.status = status;
      this.body = body;
    }
    get isValidationError() {
      return this.status === 422;
    }
    get isNetworkError() {
      return this.status === 0;
    }
  },
}));

import { SettingsForm } from "@/components/SettingsForm";

// ---------------------------------------------------------------------------
// jsdom polyfills required by the Base UI Switch internals.
// ---------------------------------------------------------------------------
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

const BOOL_ITEM: SettingItem = {
  key: "auto_status_personal_enabled",
  value: false,
  type: "bool",
  min: null,
  max: null,
  label: "تحويل الحالة الشخصية تلقائيًا",
};

function renderForm(items: SettingItem[]) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const data: SettingsResponse = { items };
  return render(
    <QueryClientProvider client={client}>
      <SettingsForm data={data} onSaved={vi.fn()} />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("SettingsForm — boolean toggles", () => {
  it("renders a bool setting as a Switch reflecting its value", () => {
    renderForm([BOOL_ITEM]);
    const sw = screen.getByRole("switch");
    expect(sw).toHaveAttribute("aria-checked", "false");
  });

  it("submits the boolean value after toggling the Switch", async () => {
    updateSettingsSpy.mockResolvedValue({
      items: [{ ...BOOL_ITEM, value: true }],
    } as SettingsResponse);

    renderForm([BOOL_ITEM]);

    fireEvent.click(screen.getByRole("switch"));
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");

    fireEvent.click(screen.getByRole("button", { name: "حفظ" }));

    await waitFor(() =>
      expect(updateSettingsSpy).toHaveBeenCalledWith({
        auto_status_personal_enabled: true,
      })
    );
  });
});
