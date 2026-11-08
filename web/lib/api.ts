// Same-origin; the Next.js route handler at app/api/[...path] proxies to FastAPI.
export const API_URL = "/api";

export interface ApiMessage {
  message: string;
  description: string;
}

const NETWORK_ERROR: ApiMessage = {
  message: "Couldn't reach the server",
  description: "Check your connection and try again.",
};

export class ApiError extends Error {
  readonly status: number;
  readonly description: string;
  readonly detail: unknown;
  /** Raw `duplicates` field of a 409 "already in your portfolio" body. */
  readonly duplicates: unknown;

  constructor(
    status: number,
    message: string,
    description: string,
    detail?: unknown,
    duplicates?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.description = description;
    this.detail = detail;
    this.duplicates = duplicates;
  }
}

/** Normalise any thrown value to API-provided text (network text if no response). */
export function toApiMessage(err: unknown): ApiMessage {
  if (err instanceof ApiError) {
    return { message: err.message, description: err.description };
  }
  return NETWORK_ERROR;
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

let redirectingToLogin = false;

/** Session expired: full navigation to /login (resets client state), once. */
function redirectToLogin(): void {
  if (typeof window === "undefined" || redirectingToLogin) return;
  const { pathname, search } = window.location;
  if (pathname.startsWith("/login") || pathname.startsWith("/signup")) return;
  redirectingToLogin = true;
  const target = `/login?next=${encodeURIComponent(pathname + search)}`;
  // Full navigation on purpose: resets all client state after a lost session.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(target);
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  let res: Response;
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      // FormData: the browser sets the multipart content-type and boundary.
      headers:
        body !== undefined && !isForm
          ? { "Content-Type": "application/json" }
          : undefined,
      body:
        body === undefined
          ? undefined
          : isForm
            ? (body as FormData)
            : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      0,
      NETWORK_ERROR.message,
      NETWORK_ERROR.description,
      "Network error",
    );
  }
  if (res.status === 401) redirectToLogin();
  if (!res.ok) {
    let data: Record<string, unknown> = {};
    try {
      const parsed: unknown = await res.json();
      if (parsed && typeof parsed === "object") {
        data = parsed as Record<string, unknown>;
      }
    } catch {
      // non-JSON error body
    }
    throw new ApiError(
      res.status,
      str(data.message) || res.statusText || `HTTP ${res.status}`,
      str(data.description),
      data.detail,
      data.duplicates,
    );
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>("GET", path);
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>("POST", path, body);
}

export function apiPostForm<T>(path: string, form: FormData): Promise<T> {
  return request<T>("POST", path, form);
}

export function apiPut<T>(path: string, body: unknown): Promise<T> {
  return request<T>("PUT", path, body);
}

export function apiPatch<T>(path: string, body: unknown): Promise<T> {
  return request<T>("PATCH", path, body);
}

export function apiDelete(path: string): Promise<ApiMessage | undefined> {
  return request<ApiMessage | undefined>("DELETE", path);
}
