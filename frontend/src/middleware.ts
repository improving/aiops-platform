import { NextRequest, NextResponse } from "next/server";

export const config = {
  matcher: ["/api/:path*"],
};

const backendUrl = process.env.AIOPS_BACKEND_URL || 'http://localhost:8000';

export function middleware(request: NextRequest) {
  const apiPath = request.nextUrl.pathname.replace(/^\/api/, ''); // Strip /api/
  return NextResponse.rewrite(
    new URL(
      `${backendUrl}${apiPath}${request.nextUrl.search}`
    ),
    { request }
  );
}