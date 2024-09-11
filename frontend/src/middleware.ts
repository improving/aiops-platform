import { NextRequest, NextResponse } from "next/server";

export const config = {
  matcher: ["/api/v1alpha1/:path*"],
};

const backendUrl = process.env.AIOPS_BACKEND_URL || "http://localhost:8000";

export function middleware(request: NextRequest) {
  if (request.nextUrl.pathname.startsWith("/api/v1alpha1")) {
    const apiPath = request.nextUrl.pathname.replace(/^\/api/, "");
    return NextResponse.rewrite(
      new URL(`${backendUrl}${apiPath}${request.nextUrl.search}`),
      { request }
    );
  }
}
