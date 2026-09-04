import { NextRequest, NextResponse } from "next/server"
import { BACKEND_URL } from "./constants"

// AIOPS_BACKEND_URL is read on the server at request time, so a container
// can point at a different backend without a rebuild. NEXT_PUBLIC_* values
// are inlined at build time and only serve as the fallback.
function backendUrl(): string {
  return process.env.AIOPS_BACKEND_URL || BACKEND_URL
}

export const config = {
  matcher: ["/api/v1alpha1/:path*"],
}

export function proxy(request: NextRequest) {
  if (request.nextUrl.pathname.startsWith("/api/v1alpha1")) {
    const apiPath = request.nextUrl.pathname.replace(/^\/api/, "")
    return NextResponse.rewrite(
      new URL(`${backendUrl()}${apiPath}${request.nextUrl.search}`),
      { request }
    )
  }
}
