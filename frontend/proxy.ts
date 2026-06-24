import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "mn_session";

/**
 * Redirect unauthenticated requests to /login.
 *
 * (Next 16 renamed the `middleware` file convention to `proxy`.)
 *
 * Auth is gated on the presence of the `mn_session` cookie. If auth is
 * disabled on the backend, the cookie-less user lands on /login which calls
 * /api/auth/status and bounces straight back to the requested page — a single
 * acceptable extra hop.
 */
export function proxy(request: NextRequest) {
  const hasSession = request.cookies.has(SESSION_COOKIE);
  if (hasSession) return NextResponse.next();

  const { pathname, search } = request.nextUrl;
  const loginUrl = new URL("/login", request.url);
  loginUrl.searchParams.set("next", `${pathname}${search}`);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  // Run on everything except Next internals, static assets, the login page,
  // and any path with a file extension (images, fonts, etc.).
  matcher: ["/((?!_next/static|_next/image|login|favicon.ico|.*\\.[^/]+$).*)"],
};
