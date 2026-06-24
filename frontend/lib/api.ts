import type {
  AuthStatus,
  HomeOverview,
  ProjectDetail,
  ProjectListResponse,
  SettingsResponse,
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
  if (init?.body != null && !headers.has("Content-Type")) {
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

export function getHome(): Promise<HomeOverview> {
  return apiFetch<HomeOverview>("/api/home");
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
