// Same-origin; the Next.js route handler at app/api/[...path] proxies to FastAPI.
export const API_URL = "/api";

type ValidationItem = { loc?: (string | number)[]; msg?: string };

function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = (detail as ValidationItem[]).map((d) => {
      const field = (d.loc ?? []).filter((p) => p !== "body").join(".");
      const msg = d.msg ?? "Invalid value";
      return field ? `${field}: ${msg}` : msg;
    });
    if (parts.length) return parts.join("; ");
  }
  return fallback;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      message = detailMessage(data?.detail, message);
    } catch {
      // non-JSON error body; keep fallback message
    }
    throw new Error(message);
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

export function apiDelete(path: string): Promise<void> {
  return request<void>("DELETE", path);
}
