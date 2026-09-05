"use client";

import { useSession } from "next-auth/react";
import Dashboard from "@/components/Dashboard";
import RegistryPage from "@/components/registry/RegistryPage";
import { isAdmin } from "@/lib/roles";
import { AUTH_DISABLED } from "@/constants";

// AUTH_MODE=disabled mounts no SessionProvider (src/components/AuthProvider.tsx),
// so useSession() must never be called in that mode; the split below keeps
// the hook call in a component that only exists when auth is enabled,
// rather than calling it conditionally inside one component.
function RegistryPageWithSession() {
  const { data: session } = useSession();
  return <RegistryPage admin={isAdmin(session)} />;
}

export default function ModelRegistryRoute() {
  return (
    <Dashboard title="Model Registry">
      {AUTH_DISABLED ? <RegistryPage admin /> : <RegistryPageWithSession />}
    </Dashboard>
  );
}
