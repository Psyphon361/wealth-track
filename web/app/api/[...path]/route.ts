import type { NextRequest } from "next/server";
import { SESSION_COOKIE, gateMode, verifySessionToken } from "@/lib/session";

type Ctx = { params: Promise<{ path: string[] }> };

async function forward(req: NextRequest, ctx: Ctx): Promise<Response> {
  const mode = gateMode();
  if (mode === "misconfigured") {
    return Response.json({ detail: "Server auth is not configured" }, { status: 503 });
  }
  if (mode === "enabled") {
    const ok = await verifySessionToken(
      req.cookies.get(SESSION_COOKIE)?.value,
      process.env.SESSION_SECRET,
    );
    if (!ok) return Response.json({ detail: "Unauthorized" }, { status: 401 });
  }

  const { path } = await ctx.params;
  if (path.some((seg) => seg === "" || seg === "." || seg === ".." || /^(\.|%2e){1,2}$/i.test(seg))) {
    return Response.json({ detail: "Invalid path" }, { status: 400 });
  }
  const base = (process.env.API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
  const target = `${base}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  headers.set("accept", "application/json");
  const apiKey = process.env.API_KEY;
  if (apiKey) headers.set("x-api-key", apiKey);

  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  const body = hasBody ? await req.text() : undefined;

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: body || undefined,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return Response.json({ detail: "Upstream API unreachable" }, { status: 502 });
  }

  const out = new Headers({ "cache-control": "no-store" });
  const upstreamType = upstream.headers.get("content-type");
  if (upstreamType) out.set("content-type", upstreamType);
  const noBody = upstream.status === 204 || upstream.status === 205 || upstream.status === 304;
  return new Response(noBody ? null : upstream.body, { status: upstream.status, headers: out });
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const DELETE = forward;
