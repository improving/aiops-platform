"use client";

import Link from "next/link";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { allowedTools, type McpServer } from "@/types/mcp";
import { McpInstancePanels } from "@/components/mcp/McpInstancePanels";
import { formatDate } from "@/lib/utils";

const TRANSPORT_LABEL: Record<string, string> = {
  http: "Streamable HTTP",
  sse: "SSE (legacy)",
};

function statusLabel(server: McpServer): string {
  if (!server.enabled) return "Disabled";
  if (server.deploy && !server.deploy.usable)
    return server.deploy.status === "Failed" ? "Failed" : "Starting";
  return server.status === "connected" ? "Connected" : "Unreachable";
}

/**
 * The server detail sheet (W5): opened from a row's name, and by
 * "View tools" for a member. Admins also see "Delete…", which hands the
 * confirmation back to the caller (`McpServersPage` owns the one delete
 * dialog shared with the row menu).
 */
export function McpServerSheet({
  server,
  open,
  onOpenChange,
  admin,
  onRequestDelete,
  initialTab,
  onChanged,
}: {
  server: McpServer | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  admin: boolean;
  onRequestDelete: (server: McpServer) => void;
  /** For a deployed server: the tab to open ("settings", "logs"). */
  initialTab?: string;
  /** A deployed server changed (settings, restart): load the list again. */
  onChanged: () => void | Promise<void>;
}) {
  const toolList = server ? (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">
        Tools ({allowedTools(server).length} of {server.tools.length} allowed)
      </h3>
      <div className="space-y-2">
        {allowedTools(server).length === 0 ? (
          <p className="text-sm text-muted-foreground">No tools allowed.</p>
        ) : (
          allowedTools(server).map((tool) => (
            <div key={tool.name} className="text-sm">
              <span className="font-medium">{tool.name}</span>{" "}
              <span className="text-muted-foreground">{tool.description}</span>
            </div>
          ))
        )}
      </div>
    </div>
  ) : null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        {server && (
          <>
            <SheetHeader>
              <SheetTitle>{server.name}</SheetTitle>
              <SheetDescription>{statusLabel(server)}</SheetDescription>
            </SheetHeader>
            <div className="space-y-4 px-4">
              <p className="text-sm text-muted-foreground">
                {server.deploy
                  ? "deployed"
                  : `${server.url} · ${TRANSPORT_LABEL[server.transport]}`}
              </p>

              <div className="text-sm">
                {server.credential_mode === "none" ? (
                  <p>No credential</p>
                ) : server.credential_mode === "per_user" ? (
                  <p>
                    {server.oauth
                      ? "Each member signs in (OAuth)"
                      : "Each member brings their own credential"}{" "}
                    ·{" "}
                    {server.my_credential === "set"
                      ? "yours is connected"
                      : "yours is not connected"}
                  </p>
                ) : admin && server.credential_set_at ? (
                  <p>
                    Shared credential · set{" "}
                    {formatDate(server.credential_set_at)}
                  </p>
                ) : (
                  <p>Shared credential</p>
                )}
              </div>

              {server.deploy ? (
                <McpInstancePanels
                  key={server.deploy.instance_id}
                  server={server}
                  admin={admin}
                  initialTab={initialTab}
                  onChanged={onChanged}
                  tools={toolList}
                />
              ) : (
                toolList
              )}
            </div>
            <SheetFooter className="flex-row justify-between">
              <Button asChild variant="outline">
                <Link href={`/chat?tools=${server.name}`} prefetch={false}>
                  Try in chat
                </Link>
              </Button>
              {admin && (
                <Button
                  type="button"
                  variant="destructive"
                  onClick={() => onRequestDelete(server)}
                >
                  Delete…
                </Button>
              )}
            </SheetFooter>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
