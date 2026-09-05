import { BACKEND_URL } from "@/constants";

// AIOPS_BACKEND_URL is read on the server at request time, so a container
// can point at a different backend without a rebuild. NEXT_PUBLIC_* values
// are inlined at build time and only serve as the fallback.
export function backendUrl(): string {
  return process.env.AIOPS_BACKEND_URL || BACKEND_URL;
}
