import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { AUTH_ERROR_COOKIE, OAUTH_COOKIE, safeNext } from "@/lib/auth";

function b64url(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomToken(): string {
  return b64url(crypto.getRandomValues(new Uint8Array(32)));
}

export async function GET(request: NextRequest) {
  const { searchParams, origin: requestOrigin } = request.nextUrl;
  const next = safeNext(searchParams.get("next"));
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const secure = process.env.NODE_ENV === "production";

  if (!clientId) {
    const url = new URL("/login", requestOrigin);
    if (next !== "/dashboard") url.searchParams.set("next", next);
    const res = NextResponse.redirect(url);
    res.cookies.set(
      AUTH_ERROR_COOKIE,
      JSON.stringify({
        message: "Google sign-in isn't configured",
        description: "Use your email and password for now.",
      }),
      { httpOnly: true, secure, sameSite: "lax", path: "/", maxAge: 60 },
    );
    return res;
  }

  const origin = (process.env.APP_ORIGIN || requestOrigin).replace(/\/+$/, "");
  const state = randomToken();
  const verifier = randomToken();
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  const challenge = b64url(new Uint8Array(digest));

  const google = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  google.searchParams.set("client_id", clientId);
  google.searchParams.set("redirect_uri", `${origin}/auth/google/callback`);
  google.searchParams.set("response_type", "code");
  google.searchParams.set("scope", "openid email profile");
  google.searchParams.set("state", state);
  google.searchParams.set("code_challenge", challenge);
  google.searchParams.set("code_challenge_method", "S256");
  google.searchParams.set("prompt", "select_account");

  const res = NextResponse.redirect(google, 302);
  res.cookies.set(OAUTH_COOKIE, JSON.stringify({ state, verifier, next }), {
    httpOnly: true,
    secure,
    sameSite: "lax",
    path: "/auth/google",
    maxAge: 600,
  });
  return res;
}
