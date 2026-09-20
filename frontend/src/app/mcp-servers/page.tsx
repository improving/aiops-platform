"use client";

import { Suspense } from "react";
import Dashboard from "@/components/Dashboard";
import McpServersPage from "@/components/mcp/McpServersPage";

export default function McpServersRoute() {
  return (
    <Dashboard title="MCP servers">
      <Suspense>
        <McpServersPage />
      </Suspense>
    </Dashboard>
  );
}
