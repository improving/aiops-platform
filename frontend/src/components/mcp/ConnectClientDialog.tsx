"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CopyButton } from "@/components/CopyButton";
import { CodeSnippet } from "@/components/CodeSnippet";
import { platformApiUrl } from "@/lib/playgroundExamples";
import type { McpServer } from "@/types/mcp";

/**
 * "Connect a client" (W9): the platform's MCP endpoint plus worked
 * examples. The endpoint is the platform API host (`api.<domain>` next to
 * `ui.<domain>`), never the UI's own session proxy: a proxy request
 * without a browser session redirects to `/login`, which an IDE or SDK
 * cannot follow.
 */
export function ConnectClientDialog({
  open,
  onOpenChange,
  servers,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  servers: McpServer[];
}) {
  const [origin, setOrigin] = useState("");
  const [limit, setLimit] = useState("");

  useEffect(() => {
    setOrigin(window.location.origin);
  }, []);

  const endpoint = `${platformApiUrl(origin)}/v1alpha1/mcp`;
  const headerLine = limit ? `X-Mcp-Servers: ${limit}` : null;

  const claudeCode = [
    `claude mcp add --transport http aiops \\`,
    `  ${endpoint} \\`,
    `  --header "Authorization: Bearer $AIOPS_TOKEN"${headerLine ? " \\" : ""}`,
    ...(headerLine ? [`  --header "${headerLine}"`] : []),
  ].join("\n");

  const cursorHeaders: Record<string, string> = {
    Authorization: "Bearer <token>",
    ...(limit ? { "X-Mcp-Servers": limit } : {}),
  };
  const cursorConfig = JSON.stringify(
    {
      mcpServers: {
        aiops: {
          url: endpoint,
          headers: cursorHeaders,
        },
      },
    },
    null,
    2
  );

  const pythonHeaders = limit
    ? `{"Authorization": "Bearer <token>", "X-Mcp-Servers": "${limit}"}`
    : `{"Authorization": "Bearer <token>"}`;
  const python = [
    "import asyncio",
    "",
    "from mcp import ClientSession",
    "from mcp.client.streamable_http import streamablehttp_client",
    "",
    "",
    "async def main():",
    `    headers = ${pythonHeaders}`,
    `    async with streamablehttp_client(`,
    `        "${endpoint}", headers=headers`,
    "    ) as (read, write, _):",
    "        async with ClientSession(read, write) as session:",
    "            await session.initialize()",
    "            tools = await session.list_tools()",
    "            print(tools)",
    "",
    "",
    "asyncio.run(main())",
  ].join("\n");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Connect a client</DialogTitle>
          <DialogDescription>
            One endpoint serves every MCP server your organization allows.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <code className="flex-1 rounded bg-muted px-2 py-1 font-mono text-xs break-all">
              {endpoint}
            </code>
            <CopyButton label="MCP endpoint" text={endpoint} />
          </div>
          <p className="text-sm text-muted-foreground">
            Use a personal API token with the scope mcp.{" "}
            <Link href="/settings/tokens" className="underline">
              Create a token
            </Link>
          </p>
          <div className="space-y-2">
            <Label htmlFor="mcp-connect-limit">
              Limit to servers (optional)
            </Label>
            <Select
              value={limit || "__all__"}
              onValueChange={(v) => setLimit(v === "__all__" ? "" : v)}
            >
              <SelectTrigger
                id="mcp-connect-limit"
                aria-label="Limit to servers"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">All servers</SelectItem>
                {servers.map((server) => (
                  <SelectItem key={server.id} value={server.name}>
                    {server.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Tabs defaultValue="claude" className="w-full min-w-0">
            <TabsList>
              <TabsTrigger value="claude">Claude Code</TabsTrigger>
              <TabsTrigger value="cursor">Cursor / VS Code</TabsTrigger>
              <TabsTrigger value="python">Python</TabsTrigger>
              <TabsTrigger value="langflow">Langflow</TabsTrigger>
            </TabsList>
            <TabsContent value="claude" className="w-full min-w-0">
              <CodeSnippet
                label="Claude Code example"
                code={claudeCode}
                lang="shell"
                wrap
              />
            </TabsContent>
            <TabsContent value="cursor" className="w-full min-w-0">
              <CodeSnippet
                label="Cursor / VS Code example"
                code={cursorConfig}
                lang="json"
                wrap
              />
            </TabsContent>
            <TabsContent value="python" className="w-full min-w-0">
              <CodeSnippet
                label="Python example"
                code={python}
                lang="python"
                wrap
              />
            </TabsContent>
            <TabsContent value="langflow" className="w-full min-w-0">
              <p className="text-sm text-muted-foreground">
                Set up by the platform. In Langflow, use the MCP Tools component
                with the variables AIOPS_MCP_URL and AIOPS_MCP_TOKEN.
              </p>
            </TabsContent>
          </Tabs>
        </div>
      </DialogContent>
    </Dialog>
  );
}
