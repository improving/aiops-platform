import { NextRequest, NextResponse } from "next/server";
import type { NextFetchEvent } from "next/server";
import { auth } from "@/auth";
import { backendUrl } from "@/lib/backend";
import {
  DEV_USER_COOKIE,
  DEV_USER_HEADER,
  ORG_COOKIE,
  ORG_HEADER,
} from "@/lib/orgCookie";
import type { Session } from "next-auth";

// Everything except Next.js internals, the Auth.js routes and /api/chat:
// /api/chat is a route handler that checks the session itself and must
// answer JSON, never a redirect to /login.
export const config = {
  matcher: ["/((?!_next/|api/auth/|api/chat|favicon\\.ico).*)"],
};

const API_PREFIX = "/api/v1alpha1";
const LOGIN_PATH = "/login";
// Files served from public/ (images, icons); a page path never has a suffix.
const STATIC_FILE = /\.[a-z0-9]+$/i;

function authDisabled(): boolean {
  return process.env.AUTH_MODE === "disabled";
}

function rewriteToBackend(
  request: NextRequest,
  accessToken?: string
): NextResponse {
  const apiPath = request.nextUrl.pathname.replace(/^\/api/, "");
  const headers = new Headers(request.headers);
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  // The proxy owns both headers: a client-sent value never passes through.
  // The organization comes from the cookie the switcher sets.
  headers.delete(ORG_HEADER);
  const org = request.cookies.get(ORG_COOKIE)?.value;
  if (org) {
    headers.set(ORG_HEADER, org);
  }
  // Disabled mode only: the Playwright fast tier impersonates one of the
  // fixed dev users through this cookie (backend/auth/dev_users.py).
  headers.delete(DEV_USER_HEADER);
  const devUser = authDisabled()
    ? request.cookies.get(DEV_USER_COOKIE)?.value
    : undefined;
  if (devUser) {
    headers.set(DEV_USER_HEADER, devUser);
  }
  return NextResponse.rewrite(
    new URL(`${backendUrl()}${apiPath}${request.nextUrl.search}`),
    { request: { headers } }
  );
}

function handle(
  request: NextRequest,
  session: Session | null
): NextResponse | undefined {
  const { pathname, search } = request.nextUrl;
  // A session whose refresh token was rejected is as good as none.
  const live = session && !session.error ? session : null;

  if (pathname.startsWith(API_PREFIX)) {
    return rewriteToBackend(request, live?.accessToken);
  }
  if (authDisabled() || pathname === LOGIN_PATH || STATIC_FILE.test(pathname)) {
    return undefined;
  }
  if (!live) {
    const login = new URL(LOGIN_PATH, request.url);
    login.searchParams.set("callbackUrl", `${pathname}${search}`);
    return NextResponse.redirect(login);
  }
  return undefined;
}

// Auth.js types the wrapper for route handlers and middleware at once, which
// is not callable with a proxy signature; it is the middleware form here.
const withSession = auth((request) =>
  handle(request, request.auth)
) as unknown as (
  request: NextRequest,
  event: NextFetchEvent
) => Promise<Response>;

export function proxy(request: NextRequest, event: NextFetchEvent) {
  // Disabled mode never touches Auth.js, so it works without AUTH_SECRET
  // and without a reachable Keycloak (the e2e fast tier and CI).
  if (authDisabled()) {
    return handle(request, null);
  }
  return withSession(request, event);
}
