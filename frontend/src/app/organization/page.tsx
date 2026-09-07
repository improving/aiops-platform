"use client";

import Dashboard from "@/components/Dashboard";
import OrganizationPage from "@/components/organization/OrganizationPage";

// No session needed: useOrg() reads the membership role from the backend,
// which scopes every call by the bearer and X-Org the proxy forwards.
export default function OrganizationRoute() {
  return (
    <Dashboard title="Organization">
      <OrganizationPage />
    </Dashboard>
  );
}
