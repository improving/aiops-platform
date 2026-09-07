"use client";

import Dashboard from "@/components/Dashboard";
import TokensPage from "@/components/tokens/TokensPage";

// Reached from the user menu ("API tokens"). The backend scopes the list
// to the caller and the active organization from the forwarded headers.
export default function TokensRoute() {
  return (
    <Dashboard title="API tokens">
      <TokensPage />
    </Dashboard>
  );
}
