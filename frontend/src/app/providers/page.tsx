"use client";

import { useSession } from "next-auth/react";
import Dashboard from "@/components/Dashboard";
import ProvidersPage from "@/components/providers/ProvidersPage";
import { isAdmin } from "@/lib/roles";
import { AUTH_DISABLED } from "@/constants";

// AUTH_MODE=disabled mounts no SessionProvider (src/components/AuthProvider.tsx),
// so useSession() must never be called in that mode; the split below keeps
// the hook call in a component that only exists when auth is enabled,
// rather than calling it conditionally inside one component.
function ProvidersPageWithSession() {
  const { data: session } = useSession();
  return <ProvidersPage admin={isAdmin(session)} />;
}

export default function ProvidersRoute() {
  return (
    <Dashboard title="Providers">
      {AUTH_DISABLED ? <ProvidersPage admin /> : <ProvidersPageWithSession />}
    </Dashboard>
  );
}
