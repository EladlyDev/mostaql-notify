/// <reference types="vitest/globals" />
import {
  API_BASE,
  ApiError,
  getPersonal,
  updatePersonal,
  toggleFavorite,
  getStatuses,
  getBoard,
  moveBoardCard,
  getUploadConfig,
  listAttachments,
  uploadAttachment,
  renameAttachment,
  deleteAttachment,
  attachmentDownloadUrl,
  attachmentPreviewUrl,
  getControl,
  pauseWatcher,
  resumeWatcher,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Same fetch-mock conventions as lib/__tests__/api.test.ts (a fresh Response on
// every call because a Response body can only be read once).
// ---------------------------------------------------------------------------
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockJson(body: unknown, status = 200) {
  (global.fetch as ReturnType<typeof vi.fn>).mockImplementation(() =>
    Promise.resolve(jsonResponse(body, status))
  );
}

function mockEmpty(status = 200) {
  (global.fetch as ReturnType<typeof vi.fn>).mockImplementation(() =>
    Promise.resolve(new Response(null, { status }))
  );
}

function lastCall(): [string, RequestInit] {
  const fetchMock = global.fetch as unknown as ReturnType<typeof vi.fn>;
  const call = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
  return [call[0] as string, call[1] as RequestInit];
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Personal CRM
// ---------------------------------------------------------------------------
describe("personal record client fns", () => {
  it("getPersonal(42) → GET /api/projects/42/personal with credentials", async () => {
    mockJson({ project_id: 42 });
    const r = await getPersonal(42);
    const [url, init] = lastCall();
    expect(url).toBe(`${API_BASE}/api/projects/42/personal`);
    expect(init.method ?? "GET").toBe("GET");
    expect(init.credentials).toBe("include");
    expect(r).toEqual({ project_id: 42 });
  });

  it("updatePersonal(42, patch) → PATCH with a JSON body + content-type", async () => {
    mockJson({ project_id: 42, status: "applied" });
    const patch = { status: "applied", tags: ["a", "b"] };
    await updatePersonal(42, patch);
    const [url, init] = lastCall();
    expect(url).toBe(`${API_BASE}/api/projects/42/personal`);
    expect(init.method).toBe("PATCH");
    expect(init.body).toBe(JSON.stringify(patch));
    expect(init.credentials).toBe("include");
    expect(new Headers(init.headers).get("Content-Type")).toBe(
      "application/json"
    );
  });

  it("toggleFavorite(42) → POST /api/projects/42/personal/favorite (no body)", async () => {
    mockJson({ project_id: 42, favorite: true });
    await toggleFavorite(42);
    const [url, init] = lastCall();
    expect(url).toBe(`${API_BASE}/api/projects/42/personal/favorite`);
    expect(init.method).toBe("POST");
    expect(init.body == null).toBe(true);
    // No body → no forced JSON content-type.
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
    expect(init.credentials).toBe("include");
  });
});

// ---------------------------------------------------------------------------
// Statuses + board
// ---------------------------------------------------------------------------
describe("statuses & board client fns", () => {
  it("getStatuses() → GET /api/statuses returns the array body", async () => {
    const body = [
      { key: "lead", label: "عميل محتمل" },
      { key: "won", label: "فاز" },
    ];
    mockJson(body);
    const r = await getStatuses();
    const [url] = lastCall();
    expect(url).toBe(`${API_BASE}/api/statuses`);
    expect(r).toEqual(body);
  });

  it("getBoard() → GET /api/board", async () => {
    mockJson({ columns: [] });
    await getBoard();
    const [url, init] = lastCall();
    expect(url).toBe(`${API_BASE}/api/board`);
    expect(init.credentials).toBe("include");
  });

  it("moveBoardCard(body) → POST /api/board/move with the JSON move request", async () => {
    mockJson({ project_id: 101, status: "applied", board_position: 1 });
    const move = { project_id: 101, to_status: "applied", position: 1 };
    await moveBoardCard(move);
    const [url, init] = lastCall();
    expect(url).toBe(`${API_BASE}/api/board/move`);
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify(move));
    expect(new Headers(init.headers).get("Content-Type")).toBe(
      "application/json"
    );
  });
});

// ---------------------------------------------------------------------------
// Attachments / workspace files
// ---------------------------------------------------------------------------
describe("attachment client fns", () => {
  it("getUploadConfig() → GET /api/upload-config", async () => {
    mockJson({ allowed_types: ["pdf"], max_bytes: 5242880 });
    await getUploadConfig();
    const [url] = lastCall();
    expect(url).toBe(`${API_BASE}/api/upload-config`);
  });

  it("listAttachments(7) → GET /api/projects/7/attachments", async () => {
    mockJson({ items: [] });
    await listAttachments(7);
    const [url, init] = lastCall();
    expect(url).toBe(`${API_BASE}/api/projects/7/attachments`);
    expect(init.credentials).toBe("include");
  });

  it("uploadAttachment sends FormData and does NOT force a Content-Type (boundary must be set by the browser)", async () => {
    mockJson({ id: 1, original_name: "doc.pdf" });
    const file = new File(["hello"], "doc.pdf", { type: "application/pdf" });
    await uploadAttachment(7, file);

    const [url, init] = lastCall();
    expect(url).toBe(`${API_BASE}/api/projects/7/attachments`);
    expect(init.method).toBe("POST");

    // CRITICAL: the body must be a real FormData so the browser sets the
    // multipart boundary; a forced "application/json" Content-Type would corrupt
    // the multipart parse on the server.
    expect(init.body).toBeInstanceOf(FormData);
    const form = init.body as FormData;
    const sent = form.get("file");
    expect(sent).toBeInstanceOf(File);
    expect((sent as File).name).toBe("doc.pdf");

    // No Content-Type header was set for the multipart request.
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
    expect(init.credentials).toBe("include");
  });

  it("renameAttachment(3, 'new.pdf') → PATCH /api/attachments/3 with {original_name}", async () => {
    mockJson({ id: 3, original_name: "new.pdf" });
    await renameAttachment(3, "new.pdf");
    const [url, init] = lastCall();
    expect(url).toBe(`${API_BASE}/api/attachments/3`);
    expect(init.method).toBe("PATCH");
    expect(init.body).toBe(JSON.stringify({ original_name: "new.pdf" }));
    expect(new Headers(init.headers).get("Content-Type")).toBe(
      "application/json"
    );
  });

  it("deleteAttachment(3) → DELETE /api/attachments/3 and resolves null on an empty body", async () => {
    mockEmpty(200);
    const r = await deleteAttachment(3);
    const [url, init] = lastCall();
    expect(url).toBe(`${API_BASE}/api/attachments/3`);
    expect(init.method).toBe("DELETE");
    expect(r).toBeNull();
  });

  it("attachmentDownloadUrl / attachmentPreviewUrl build absolute stream URLs", () => {
    expect(attachmentDownloadUrl(5)).toBe(
      `${API_BASE}/api/attachments/5/download`
    );
    expect(attachmentPreviewUrl(5)).toBe(
      `${API_BASE}/api/attachments/5/preview`
    );
    // Absolute (so they work as <a>/<iframe> src against the API origin).
    expect(attachmentDownloadUrl(5).startsWith("http")).toBe(true);
    expect(attachmentPreviewUrl(5).startsWith("http")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Watcher control
// ---------------------------------------------------------------------------
describe("control client fns", () => {
  it("getControl() → GET /api/control", async () => {
    mockJson({ paused: false });
    const r = await getControl();
    const [url, init] = lastCall();
    expect(url).toBe(`${API_BASE}/api/control`);
    expect(init.credentials).toBe("include");
    expect(r).toEqual({ paused: false });
  });

  it("pauseWatcher() → POST /api/control/pause", async () => {
    mockJson({ paused: true });
    const r = await pauseWatcher();
    const [url, init] = lastCall();
    expect(url).toBe(`${API_BASE}/api/control/pause`);
    expect(init.method).toBe("POST");
    expect(r).toEqual({ paused: true });
  });

  it("resumeWatcher() → POST /api/control/resume", async () => {
    mockJson({ paused: false });
    const r = await resumeWatcher();
    const [url, init] = lastCall();
    expect(url).toBe(`${API_BASE}/api/control/resume`);
    expect(init.method).toBe("POST");
    expect(r).toEqual({ paused: false });
  });
});

// ---------------------------------------------------------------------------
// ApiError classification across Feature 3 endpoints
// ---------------------------------------------------------------------------
describe("ApiError classification", () => {
  it("404 → status 404, not unauthorized / validation / network", async () => {
    mockJson({ detail: "Not found" }, 404);
    const err = await getPersonal(99).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.isUnauthorized).toBe(false);
    expect(err.isValidationError).toBe(false);
    expect(err.isNetworkError).toBe(false);
    expect(err.message).toBe("Not found");
  });

  it("422 → isValidationError true with the parsed body", async () => {
    const body = { detail: "Validation failed", errors: { status: "bad" } };
    mockJson(body, 422);
    const err = await updatePersonal(1, { status: "nope" }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.isValidationError).toBe(true);
    expect(err.isUnauthorized).toBe(false);
    expect((err.body as typeof body).errors).toEqual({ status: "bad" });
  });

  it("401 → isUnauthorized true", async () => {
    mockJson({ detail: "Unauthorized" }, 401);
    const err = await getBoard().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.isUnauthorized).toBe(true);
    expect(err.status).toBe(401);
  });

  it("a thrown fetch (network failure) → isNetworkError true with status 0", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockRejectedValue(
      new TypeError("Failed to fetch")
    );
    const err = await getControl().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.isNetworkError).toBe(true);
    expect(err.status).toBe(0);
  });
});
