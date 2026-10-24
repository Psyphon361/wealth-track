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

  constructor(
    status: number,
    message: string,
    description: string,
    detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.description = description;
    this.detail = detail;
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

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
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

export function apiPut<T>(path: string, body: unknown): Promise<T> {
  return request<T>("PUT", path, body);
}

export function apiDelete(path: string): Promise<ApiMessage | undefined> {
  return request<ApiMessage | undefined>("DELETE", path);
}
