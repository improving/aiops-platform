"use client";

import Dashboard from "@/components/Dashboard";
import McpServersPage from "@/components/mcp/McpServersPage";

export default function McpServersRoute() {
  return (
    <Dashboard title="MCP servers">
      <McpServersPage />
    </Dashboard>
  );
}
