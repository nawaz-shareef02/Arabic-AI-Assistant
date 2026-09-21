import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  /**
   * P2-1 Security Notice:
   * Next.js Middleware inspects request cookies for UI client navigation routing hints.
   * Note: The presence of a cookie in middleware is only a UI navigation convenience hint.
   * Real security boundaries and authorization enforcement are performed exclusively on the
   * backend FastAPI server through cryptographically validated HttpOnly auth_token cookies.
   */
  const hasAuthHint =
    request.cookies.has("auth_token") || request.cookies.has("csrf_token");

  // Route matches
  const isAuthPage =
    pathname.startsWith("/login") ||
    pathname.startsWith("/register") ||
    pathname.startsWith("/forgot-password") ||
    pathname.startsWith("/session-expired");

  const isProtectedPage =
    pathname.startsWith("/dashboard") ||
    pathname.startsWith("/chat") ||
    pathname.startsWith("/documents") ||
    pathname.startsWith("/upload") ||
    pathname.startsWith("/analytics") ||
    pathname.startsWith("/settings") ||
    pathname.startsWith("/models") ||
    pathname.startsWith("/select-workspace");

  // Redirect unauthenticated requests to login
  if (isProtectedPage && !hasAuthHint) {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  // Redirect authenticated requests away from authentication views to dashboard
  if (isAuthPage && hasAuthHint) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

// Configured matching path rules
export const config = {
  matcher: [
    "/dashboard/:path*",
    "/chat/:path*",
    "/documents/:path*",
    "/upload/:path*",
    "/analytics/:path*",
    "/settings/:path*",
    "/models/:path*",
    "/select-workspace",
    "/login",
    "/register",
    "/forgot-password",
    "/session-expired",
  ],
};
