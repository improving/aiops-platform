"use client";

import Dashboard from "@/components/Dashboard";
import UsagePage from "@/components/usage/UsagePage";

// No session needed here: the backend reads the caller from the bearer
// token forwarded by the proxy and scopes the response itself (members get
// their own rows, admins the whole organization).
export default function UsageRoute() {
  return (
    <Dashboard title="Usage">
      <UsagePage />
    </Dashboard>
  );
}
