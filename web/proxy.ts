import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { REFRESH_COOKIE } from "@/lib/auth";

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const isApi = pathname === "/api" || pathname.startsWith("/api/");
  const hasRefresh = Boolean(request.cookies.get(REFRESH_COOKIE)?.value);

  if (isApi) {
    // The access cookie expires after 15 min and the browser drops it; the route
    // handler refreshes it from the refresh cookie, so only the refresh cookie is required.
    if (hasRefresh) return NextResponse.next();
    return NextResponse.json(
      { message: "Not logged in", description: "Log in to continue.", detail: "Unauthorized" },
      { status: 401 },
    );
  }

  if (pathname === "/auth/google/start" || pathname === "/auth/google/callback") {
    return NextResponse.next();
  }

  // Files from web/public (og.png, logo.svg, ...) are public.
  if (/\.[a-z0-9]+$/i.test(pathname)) return NextResponse.next();

  // The landing page is public for everyone; /welcome is the old address.
  if (pathname === "/welcome" || pathname.startsWith("/welcome/")) {
    return NextResponse.redirect(new URL("/", request.url), 308);
  }
  if (pathname === "/") return NextResponse.next();

  const isAuthPage =
    pathname === "/login" ||
    pathname.startsWith("/login/") ||
    pathname === "/signup" ||
    pathname.startsWith("/signup/");
  if (isAuthPage) {
    if (hasRefresh) return NextResponse.redirect(new URL("/dashboard", request.url));
    return NextResponse.next();
  }
  if (hasRefresh) return NextResponse.next();

  const url = new URL("/login", request.url);
  url.searchParams.set("next", pathname + search);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/((?!_next/static/|_next/image|favicon\\.ico$).*)"],
};
