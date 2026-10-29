import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import {
  AUTH_ERROR_COOKIE,
  OAUTH_COOKIE,
  apiAuthFetch,
  safeNext,
  setAuthCookies,
  type TokenResponse,
} from "@/lib/auth";

const FALLBACK = {
  message: "Google sign-in failed",
  description: "Try again, or log in with your email.",
};

export async function GET(request: NextRequest) {
  const { searchParams, origin: requestOrigin } = request.nextUrl;
  const secure = process.env.NODE_ENV === "production";

  let stored: { state?: string; verifier?: string; next?: string } = {};
  try {
    const raw = request.cookies.get(OAUTH_COOKIE)?.value;
    if (raw) stored = JSON.parse(raw);
  } catch {
    stored = {};
  }
  const next = safeNext(stored.next);

  function finish(res: NextResponse): NextResponse {
    res.cookies.set(OAUTH_COOKIE, "", { path: "/auth/google", maxAge: 0 });
    return res;
  }

  function fail(error: { message: string; description: string }): NextResponse {
    const url = new URL("/login", requestOrigin);
    if (next !== "/") url.searchParams.set("next", next);
    const res = NextResponse.redirect(url);
    res.cookies.set(AUTH_ERROR_COOKIE, JSON.stringify(error), {
      httpOnly: true,
      secure,
      sameSite: "lax",
      path: "/",
      maxAge: 60,
    });
    return finish(res);
  }

  const code = searchParams.get("code");
  const state = searchParams.get("state");
  if (
    searchParams.get("error") ||
    !code ||
    !state ||
    !stored.state ||
    !stored.verifier ||
    state !== stored.state
  ) {
    return fail(FALLBACK);
  }

  const origin = (process.env.APP_ORIGIN || requestOrigin).replace(/\/+$/, "");
  let res: Response;
  try {
    res = await apiAuthFetch("google", {
      code,
      code_verifier: stored.verifier,
      redirect_uri: `${origin}/auth/google/callback`,
    });
  } catch {
    return fail({
      message: "Couldn't reach the server",
      description: "Check your connection and try again.",
    });
  }

  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }

  if (!res.ok) {
    const body = (data ?? {}) as { message?: string; description?: string };
    return fail({
      message: body.message ?? FALLBACK.message,
      description: body.description ?? FALLBACK.description,
    });
  }

  const ok = NextResponse.redirect(new URL(next, requestOrigin));
  setAuthCookies(ok.cookies, data as TokenResponse);
  return finish(ok);
}
