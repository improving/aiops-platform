import { NextRequest, NextResponse } from "next/server"
import { BACKEND_URL } from "./constants"

export const config = {
  matcher: ["/api/v1alpha1/:path*"],
}

export function middleware(request: NextRequest) {
  if (request.nextUrl.pathname.startsWith("/api/v1alpha1")) {
    const apiPath = request.nextUrl.pathname.replace(/^\/api/, "")
    return NextResponse.rewrite(
      new URL(`${BACKEND_URL}${apiPath}${request.nextUrl.search}`),
      { request }
    )
  }
}
