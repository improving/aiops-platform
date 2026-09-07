"use client";

import Dashboard from "@/components/Dashboard";
import AuditPage from "@/components/audit/AuditPage";

// The user menu links here for admins only; the page checks the membership
// role through useOrg() and the API enforces require_admin regardless.
export default function AuditRoute() {
  return (
    <Dashboard title="Audit log">
      <AuditPage />
    </Dashboard>
  );
}
