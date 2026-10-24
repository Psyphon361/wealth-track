import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { SESSION_COOKIE, gateMode, verifySessionToken } from "@/lib/session";

export async function proxy(request: NextRequest) {
  const mode = gateMode();
  if (mode === "disabled") return NextResponse.next();

  const { pathname, search } = request.nextUrl;
  const isApi = pathname === "/api" || pathname.startsWith("/api/");

  if (mode === "misconfigured") {
    if (isApi) {
      return NextResponse.json({
          message: "Server not configured",
          description: "Login is not set up on this deployment.",
          detail: "Server auth is not configured",
        }, { status: 503 });
    }
    if (pathname === "/login") return NextResponse.next();
    return NextResponse.redirect(new URL("/login", request.url));
  }

  const ok = await verifySessionToken(
    request.cookies.get(SESSION_COOKIE)?.value,
    process.env.SESSION_SECRET,
  );
  if (ok) return NextResponse.next();

  if (isApi) {
    return NextResponse.json({
      message: "Not logged in",
      description: "Log in to continue.",
      detail: "Unauthorized",
    }, { status: 401 });
  }
  const url = new URL("/login", request.url);
  url.searchParams.set("next", pathname + search);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!login(?:/|$)|_next/static/|_next/image|favicon\\.ico$).*)"],
};
