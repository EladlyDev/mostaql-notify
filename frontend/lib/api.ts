import type {
  AnalyticsOverview,
  AttachmentItem,
  AttachmentListResponse,
  AuthStatus,
  BoardMoveRequest,
  BoardCard,
  BoardResponse,
  ControlState,
  HomeOverview,
  Lifecycle,
  PersonalRecord,
  PersonalStatusOption,
  PersonalUpdate,
  ProjectDetail,
  ProjectListResponse,
  SettingsResponse,
  UploadConfig,
} from "@/lib/types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// Sentinel status used when the request never reached the server
// (network failure / backend unreachable) so screens can show a
// dedicated "backend unreachable" error state.
export const NETWORK_ERROR_STATUS = 0;

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }

  get isNetworkError(): boolean {
    return this.status === NETWORK_ERROR_STATUS;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isValidationError(): boolean {
    return this.status === 422;
  }
}

async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/**
 * Core typed fetch wrapper.
 * - Always sends the session cookie (`credentials: "include"`).
 * - Sets JSON Content-Type when a body is present.
 * - Throws a typed {@link ApiError} on non-2xx (carrying status + parsed body).
 * - Throws an {@link ApiError} with {@link NETWORK_ERROR_STATUS} on transport failure.
 */
export async function apiFetch<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;

  const headers = new Headers(init?.headers);
  // Don't force a JSON content-type for multipart uploads — the browser must set the multipart
  // boundary itself (Feature 3 attachment uploads send FormData).
  const isFormData =
    typeof FormData !== "undefined" && init?.body instanceof FormData;
  if (init?.body != null && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers,
      credentials: "include",
    });
  } catch (err) {
    throw new ApiError(
      NETWORK_ERROR_STATUS,
      err instanceof Error ? err.message : "Network request failed"
    );
  }

  const body = await parseBody(res);

  if (!res.ok) {
    let message = `Request failed with status ${res.status}`;
    if (
      body &&
      typeof body === "object" &&
      "detail" in body &&
      typeof (body as { detail: unknown }).detail === "string"
    ) {
      message = (body as { detail: string }).detail;
    }
    throw new ApiError(res.status, message, body);
  }

  return body as T;
}

function buildQuery(
  params: Record<string, string | number | boolean | undefined>
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export function login(password: string): Promise<AuthStatus> {
  return apiFetch<AuthStatus>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}

export function logout(): Promise<AuthStatus> {
  return apiFetch<AuthStatus>("/api/auth/logout", { method: "POST" });
}

export function getAuthStatus(): Promise<AuthStatus> {
  return apiFetch<AuthStatus>("/api/auth/status");
}

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

export function getProjects(
  params: Record<string, string | number | boolean | undefined> = {}
): Promise<ProjectListResponse> {
  return apiFetch<ProjectListResponse>(`/api/projects${buildQuery(params)}`);
}

export function getProject(id: number | string): Promise<ProjectDetail> {
  return apiFetch<ProjectDetail>(`/api/projects/${id}`);
}

// ---------------------------------------------------------------------------
// Feature 4 — opportunity score, lifecycle, and auto-status revert
// ---------------------------------------------------------------------------

// The project's append-only lifecycle: bid/status/score trajectory, deduped
// status timeline, and final outcome.
export function getLifecycle(id: number | string): Promise<Lifecycle> {
  return apiFetch<Lifecycle>(`/api/projects/${id}/lifecycle`);
}

// Undo a watcher-applied automatic status change, restoring the prior stage.
// Returns the refreshed personal record.
export function revertAutoStatus(
  id: number | string
): Promise<PersonalRecord> {
  return apiFetch<PersonalRecord>(
    `/api/projects/${id}/personal/revert-auto-status`,
    { method: "POST" }
  );
}

export function getHome(): Promise<HomeOverview> {
  return apiFetch<HomeOverview>("/api/home");
}

// ---------------------------------------------------------------------------
// Feature 6 — read-only analytics overview (all sections + tips for a date range)
// ---------------------------------------------------------------------------

export function getAnalyticsOverview(
  params: Record<string, string | number | boolean | undefined> = {}
): Promise<AnalyticsOverview> {
  return apiFetch<AnalyticsOverview>(`/api/analytics/overview${buildQuery(params)}`);
}

export function getSettings(): Promise<SettingsResponse> {
  return apiFetch<SettingsResponse>("/api/settings");
}

export function updateSettings(
  patch: Record<string, number>
): Promise<SettingsResponse> {
  return apiFetch<SettingsResponse>("/api/settings", {
    method: "PUT",
    body: JSON.stringify(patch),
  });
}

// ---------------------------------------------------------------------------
// Feature 3 — personal pipeline & workspace
// ---------------------------------------------------------------------------

// Personal record (CRM core)
export function getPersonal(projectId: number): Promise<PersonalRecord> {
  return apiFetch<PersonalRecord>(`/api/projects/${projectId}/personal`);
}

export function updatePersonal(
  projectId: number,
  patch: PersonalUpdate
): Promise<PersonalRecord> {
  return apiFetch<PersonalRecord>(`/api/projects/${projectId}/personal`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function toggleFavorite(projectId: number): Promise<PersonalRecord> {
  return apiFetch<PersonalRecord>(
    `/api/projects/${projectId}/personal/favorite`,
    { method: "POST" }
  );
}

// Configured pipeline stages (slug + Arabic label) for the status pickers.
export function getStatuses(): Promise<PersonalStatusOption[]> {
  return apiFetch<PersonalStatusOption[]>("/api/statuses");
}

// Kanban board
export function getBoard(): Promise<BoardResponse> {
  return apiFetch<BoardResponse>("/api/board");
}

export function moveBoardCard(body: BoardMoveRequest): Promise<BoardCard> {
  return apiFetch<BoardCard>("/api/board/move", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// Attachments (workspace files)
export function getUploadConfig(): Promise<UploadConfig> {
  return apiFetch<UploadConfig>("/api/upload-config");
}

export function listAttachments(
  projectId: number
): Promise<AttachmentListResponse> {
  return apiFetch<AttachmentListResponse>(
    `/api/projects/${projectId}/attachments`
  );
}

export function uploadAttachment(
  projectId: number,
  file: File
): Promise<AttachmentItem> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<AttachmentItem>(`/api/projects/${projectId}/attachments`, {
    method: "POST",
    body: form,
  });
}

export function renameAttachment(
  attachmentId: number,
  originalName: string
): Promise<AttachmentItem> {
  return apiFetch<AttachmentItem>(`/api/attachments/${attachmentId}`, {
    method: "PATCH",
    body: JSON.stringify({ original_name: originalName }),
  });
}

export function deleteAttachment(attachmentId: number): Promise<null> {
  return apiFetch<null>(`/api/attachments/${attachmentId}`, {
    method: "DELETE",
  });
}

// Absolute URLs for the gated download/preview streams (used in <a>/<iframe> src).
export function attachmentDownloadUrl(attachmentId: number): string {
  return `${API_BASE}/api/attachments/${attachmentId}/download`;
}

export function attachmentPreviewUrl(attachmentId: number): string {
  return `${API_BASE}/api/attachments/${attachmentId}/preview`;
}

// Watcher control (mirrors Telegram /pause /resume)
export function getControl(): Promise<ControlState> {
  return apiFetch<ControlState>("/api/control");
}

export function pauseWatcher(): Promise<ControlState> {
  return apiFetch<ControlState>("/api/control/pause", { method: "POST" });
}

export function resumeWatcher(): Promise<ControlState> {
  return apiFetch<ControlState>("/api/control/resume", { method: "POST" });
}
