// Server-only helpers (cookies, API auth calls). Do not import from client components.
export const ACCESS_COOKIE = "wt_access";
export const REFRESH_COOKIE = "wt_refresh";
export const OAUTH_COOKIE = "wt_oauth";
export const AUTH_ERROR_COOKIE = "wt_auth_error";
export const ACCESS_MAX_AGE_SECONDS = 15 * 60;
export const REFRESH_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

export type TokenResponse = {
  access_token: string;
  access_expires_at: string;
  refresh_token: string;
  refresh_expires_at: string;
  user: { id: string | number; email: string };
};

export type CookieSetter = {
  set: (name: string, value: string, options: Record<string, unknown>) => unknown;
  delete: (name: string) => unknown;
};

function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
}

export function setAuthCookies(store: CookieSetter, tokens: TokenResponse): void {
  store.set(ACCESS_COOKIE, tokens.access_token, cookieOptions(ACCESS_MAX_AGE_SECONDS));
  store.set(REFRESH_COOKIE, tokens.refresh_token, cookieOptions(REFRESH_MAX_AGE_SECONDS));
}

export function clearAuthCookies(store: CookieSetter): void {
  store.delete(ACCESS_COOKIE);
  store.delete(REFRESH_COOKIE);
}

/** Only allow same-origin relative paths. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) {
    return "/";
  }
  return next;
}

/** Reads a JWT's `exp` (seconds since epoch) WITHOUT verifying the signature. */
export function jwtExp(token: string | undefined): number | null {
  if (!token) return null;
  const part = token.split(".")[1];
  if (!part) return null;
  try {
    const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
    const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
    const exp = (JSON.parse(atob(padded)) as { exp?: unknown }).exp;
    return typeof exp === "number" ? exp : null;
  } catch {
    return null;
  }
}

export function apiBase(): string {
  return (process.env.API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
}

/** POSTs JSON to `${API_URL}/api/auth/<path>` with the API key. Throws on network failure. */
export async function apiAuthFetch(path: string, body: unknown): Promise<Response> {
  const headers = new Headers({
    "content-type": "application/json",
    accept: "application/json",
  });
  const apiKey = process.env.API_KEY;
  if (apiKey) headers.set("x-api-key", apiKey);
  return fetch(`${apiBase()}/api/auth/${path.replace(/^\/+/, "")}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    cache: "no-store",
    redirect: "manual",
  });
}

export type AuthError = { message: string; description: string | null };

/** Parses the short-lived wt_auth_error cookie value (set by the Google OAuth routes). */
export function parseAuthError(raw: string | undefined): AuthError | null {
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as { message?: unknown; description?: unknown };
    if (typeof v.message !== "string" || !v.message) return null;
    return { message: v.message, description: typeof v.description === "string" ? v.description : null };
  } catch {
    return null;
  }
}
