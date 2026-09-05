"use client";

import { SessionProvider } from "next-auth/react";
import { AUTH_DISABLED } from "@/constants";

// In disabled mode there is no Auth.js session to poll, so the provider is
// left out and `UserMenu` is never rendered.
export function AuthProvider({ children }: { children: React.ReactNode }) {
  if (AUTH_DISABLED) return <>{children}</>;
  return <SessionProvider>{children}</SessionProvider>;
}
