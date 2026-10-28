import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  apiAuthFetch,
  apiBase,
  clearAuthCookies,
  jwtExp,
  setAuthCookies,
  type TokenResponse,
} from "@/lib/auth";

type Ctx = { params: Promise<{ path: string[] }> };

const REFRESH_SKEW_SECONDS = 30;

async function refreshTokens(refreshToken: string): Promise<TokenResponse | null> {
  try {
    const res = await apiAuthFetch("refresh", { refresh_token: refreshToken });
    if (!res.ok) return null;
    return (await res.json()) as TokenResponse;
  } catch {
    return null;
  }
}

function notAuthorised(): NextResponse {
  const res = NextResponse.json(
    {
      message: "Not authorised",
      description: "Your session may have expired. Log in again.",
      detail: "Unauthorized",
    },
    { status: 401, headers: { "cache-control": "no-store" } },
  );
  clearAuthCookies(res.cookies);
  return res;
}

async function forward(req: NextRequest, ctx: Ctx): Promise<Response> {
  const { path } = await ctx.params;
  if (path.some((seg) => seg === "" || seg === "." || seg === ".." || /^(\.|%2e){1,2}$/i.test(seg))) {
    return Response.json({ message: "Bad request", description: "Invalid API path.", detail: "Bad path" }, { status: 400 });
  }
  // Auth endpoints are reachable only through server actions; /api/me maps to /auth/me.
  let upstreamPath = path;
  if (path.length === 1 && path[0] === "me") {
    if (req.method !== "GET") {
      return Response.json({ message: "Not found", description: "That API route does not exist.", detail: "Not found" }, { status: 404 });
    }
    upstreamPath = ["auth", "me"];
  } else if (path[0].toLowerCase() === "auth") {
    return Response.json({ message: "Not found", description: "That API route does not exist.", detail: "Not found" }, { status: 404 });
  }

  let access = req.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = req.cookies.get(REFRESH_COOKIE)?.value;
  if (!access && !refresh) {
    return Response.json(
      { message: "Not logged in", description: "Log in to continue.", detail: "Unauthorized" },
      { status: 401 },
    );
  }

  let fresh: TokenResponse | null = null;
  let refreshTried = false;
  const exp = jwtExp(access);
  if (refresh && (!access || exp === null || exp - Date.now() / 1000 < REFRESH_SKEW_SECONDS)) {
    refreshTried = true;
    fresh = await refreshTokens(refresh);
    if (!fresh) return notAuthorised();
    access = fresh.access_token;
  }

  const target = `${apiBase()}/api/${upstreamPath.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  const body = hasBody ? await req.text() : undefined;
  const contentType = req.headers.get("content-type");

  const call = (token: string | undefined) => {
    const headers = new Headers();
    if (contentType) headers.set("content-type", contentType);
    headers.set("accept", "application/json");
    const apiKey = process.env.API_KEY;
    if (apiKey) headers.set("x-api-key", apiKey);
    if (token) headers.set("authorization", `Bearer ${token}`);
    return fetch(target, {
      method: req.method,
      headers,
      body: body || undefined,
      cache: "no-store",
      redirect: "manual",
    });
  };

  let upstream: Response;
  try {
    upstream = await call(access);
    if (upstream.status === 401 && refresh && !refreshTried) {
      fresh = await refreshTokens(refresh);
      if (!fresh) return notAuthorised();
      access = fresh.access_token;
      upstream = await call(access);
    }
  } catch {
    return Response.json({
        message: "Couldn't reach the server",
        description: "The API is unavailable. Try again shortly.",
        detail: "Upstream API unreachable",
      }, { status: 502 });
  }

  const out = new Headers({ "cache-control": "no-store" });
  const upstreamType = upstream.headers.get("content-type");
  if (upstreamType) out.set("content-type", upstreamType);
  const noBody = upstream.status === 204 || upstream.status === 205 || upstream.status === 304;
  const res = new NextResponse(noBody ? null : upstream.body, { status: upstream.status, headers: out });
  if (fresh) setAuthCookies(res.cookies, fresh);
  return res;
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
