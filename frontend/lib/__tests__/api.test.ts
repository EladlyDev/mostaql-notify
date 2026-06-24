/// <reference types="vitest/globals" />
import {
  API_BASE,
  ApiError,
  getProjects,
  getProject,
  getHome,
  getSettings,
  updateSettings,
  login,
  logout,
} from "@/lib/api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// A Response body can only be read once, so return a FRESH Response on every
// fetch invocation (some tests call the same endpoint twice).
function mockJson(body: unknown, status = 200) {
  (global.fetch as ReturnType<typeof vi.fn>).mockImplementation(() =>
    Promise.resolve(jsonResponse(body, status))
  );
}

function lastCall() {
  const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
  return fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("getProjects query building", () => {
  it("includes set params and omits empty / undefined ones", async () => {
    mockJson({ items: [], total: 0 });

    await getProjects({
      tier: 1,
      q: "",
      site_status: undefined,
      qualified_only: true,
      page: 2,
    });

    const [url, init] = lastCall();
    const u = new URL(url as string);
    expect(u.pathname).toBe("/api/projects");
    expect(u.searchParams.get("tier")).toBe("1");
    expect(u.searchParams.get("qualified_only")).toBe("true");
    expect(u.searchParams.get("page")).toBe("2");
    // empty string and undefined are skipped
    expect(u.searchParams.has("q")).toBe(false);
    expect(u.searchParams.has("site_status")).toBe(false);
    expect((init as RequestInit).credentials).toBe("include");
  });
});

describe("GET endpoints", () => {
  it("getProject(5) → GET /api/projects/5", async () => {
    mockJson({ id: 5 });
    const r = await getProject(5);
    const [url, init] = lastCall();
    expect(url).toBe(`${API_BASE}/api/projects/5`);
    // GET → no explicit method set
    expect((init as RequestInit).method ?? "GET").toBe("GET");
    expect((init as RequestInit).credentials).toBe("include");
    expect(r).toEqual({ id: 5 });
  });

  it("getHome() → GET /api/home", async () => {
    mockJson({ ok: true });
    await getHome();
    const [url, init] = lastCall();
    expect(url).toBe(`${API_BASE}/api/home`);
    expect((init as RequestInit).credentials).toBe("include");
  });

  it("getSettings() → GET /api/settings", async () => {
    mockJson({ budget_primary_floor: 100 });
    await getSettings();
    const [url] = lastCall();
    expect(url).toBe(`${API_BASE}/api/settings`);
  });
});

describe("mutating endpoints", () => {
  it("login('pw') → POST /api/auth/login with JSON body + content-type", async () => {
    mockJson({ authenticated: true });
    await login("pw");
    const [url, init] = lastCall();
    const ri = init as RequestInit;
    expect(url).toBe(`${API_BASE}/api/auth/login`);
    expect(ri.method).toBe("POST");
    expect(ri.body).toBe(JSON.stringify({ password: "pw" }));
    expect(ri.credentials).toBe("include");
    const headers = new Headers(ri.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("logout() → POST /api/auth/logout", async () => {
    mockJson({ authenticated: false });
    await logout();
    const [url, init] = lastCall();
    expect(url).toBe(`${API_BASE}/api/auth/logout`);
    expect((init as RequestInit).method).toBe("POST");
  });

  it("updateSettings({budget_primary_floor:300}) → PUT /api/settings with body", async () => {
    mockJson({ budget_primary_floor: 300 });
    await updateSettings({ budget_primary_floor: 300 });
    const [url, init] = lastCall();
    const ri = init as RequestInit;
    expect(url).toBe(`${API_BASE}/api/settings`);
    expect(ri.method).toBe("PUT");
    expect(ri.body).toBe(JSON.stringify({ budget_primary_floor: 300 }));
    const headers = new Headers(ri.headers);
    expect(headers.get("Content-Type")).toBe("application/json");
  });
});

describe("error mapping", () => {
  it("401 → ApiError with isUnauthorized true", async () => {
    mockJson({ detail: "Unauthorized" }, 401);
    await expect(getHome()).rejects.toMatchObject({ status: 401 });
    const err = await getHome().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.isUnauthorized).toBe(true);
    expect(err.message).toBe("Unauthorized");
  });

  it("422 → isValidationError true and parsed errors accessible", async () => {
    const body = {
      detail: "Validation failed",
      errors: { budget_primary_floor: "must be >= 0" },
    };
    mockJson(body, 422);
    const err = await updateSettings({ budget_primary_floor: -1 }).catch(
      (e) => e
    );
    expect(err).toBeInstanceOf(ApiError);
    expect(err.isValidationError).toBe(true);
    expect((err.body as typeof body).errors).toEqual({
      budget_primary_floor: "must be >= 0",
    });
  });

  it("503 → ApiError with status 503", async () => {
    mockJson({ detail: "unavailable" }, 503);
    const err = await getHome().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(503);
    expect(err.isUnauthorized).toBe(false);
    expect(err.isNetworkError).toBe(false);
  });

  it("network rejection → ApiError with isNetworkError true (status 0)", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockRejectedValue(
      new TypeError("Failed to fetch")
    );
    const err = await getHome().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.isNetworkError).toBe(true);
    expect(err.status).toBe(0);
  });

  it("200 with JSON → returns the parsed value", async () => {
    mockJson({ value: 42 });
    const r = await getHome();
    expect(r).toEqual({ value: 42 });
  });
});

describe("credentials: include on every call", () => {
  it("is sent for GET and mutating calls", async () => {
    mockJson({});
    await getHome();
    expect((lastCall()[1] as RequestInit).credentials).toBe("include");
    await login("x");
    expect((lastCall()[1] as RequestInit).credentials).toBe("include");
  });
});
