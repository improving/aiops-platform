"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DotsHorizontalIcon } from "@radix-ui/react-icons";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";
import { useOrg } from "@/hooks/useOrg";
import { mcpService } from "@/services/mcpService";
import { allowedTools, type McpScope, type McpServer } from "@/types/mcp";
import { TableSkeleton } from "@/components/LoadingState";
import { ConnectCredentialDialog } from "@/components/mcp/ConnectCredentialDialog";
import { AddMcpServerDialog } from "@/components/mcp/AddMcpServerDialog";
import { EditToolsDialog } from "@/components/mcp/EditToolsDialog";
import { ChangeCredentialDialog } from "@/components/mcp/ChangeCredentialDialog";
import { McpServerSheet } from "@/components/mcp/McpServerSheet";
import { ConnectClientDialog } from "@/components/mcp/ConnectClientDialog";

const TRY_ONE_LINKS = [
  { name: "deepwiki", label: "DeepWiki", url: "https://mcp.deepwiki.com/mcp" },
  { name: "context7", label: "Context7", url: "https://mcp.context7.com/mcp" },
];

function hostAndPath(url: string): string {
  try {
    const parsed = new URL(url);
    return `${parsed.host}${parsed.pathname}`;
  } catch {
    return url;
  }
}

function statusLabel(server: McpServer): {
  text: string;
  className: string;
} {
  if (!server.enabled) {
    return { text: "Disabled", className: "bg-gray-100 text-gray-800" };
  }
  if (server.status === "connected") {
    return { text: "Connected", className: "bg-green-100 text-green-800" };
  }
  return { text: "Unreachable", className: "bg-amber-100 text-amber-800" };
}

function toolsLabel(server: McpServer): string {
  const total = server.tools.length;
  if (total === 0) return "–";
  if (server.allowed_tools === null) return String(total);
  return `${allowedTools(server).length} / ${total}`;
}

function relativeTime(iso: string | null): string {
  if (!iso) return "–";
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h`;
  const days = Math.round(hours / 24);
  return `${days} d`;
}

/**
 * `/mcp-servers` (Phase 3, W1/W4/W5/W9): an organization's remote MCP
 * servers. Admin gating follows `useOrg()`, not `session.roles`, like the
 * rest of the organization surfaces -- the backend enforces `require_admin`
 * on every write regardless.
 */
export default function McpServersPage() {
  const { toast } = useToast();
  const { isAdmin, isPlatformAdmin, role, loading: orgLoading } = useOrg();
  const isViewer = role === "viewer";
  // What this user may add, the default first. Anyone who can use tools
  // can add a server for themselves.
  const addScopes: McpScope[] = [
    ...(isAdmin ? (["organization"] as const) : []),
    ...(!isViewer ? (["personal"] as const) : []),
    ...(isPlatformAdmin ? (["platform"] as const) : []),
  ];
  const canAdd = addScopes.length > 0;
  const [connectServer, setConnectServer] = useState<McpServer | null>(null);
  const [servers, setServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [litellmError, setLitellmError] = useState<string | null>(null);

  const [addOpen, setAddOpen] = useState(false);
  const [addInitial, setAddInitial] = useState<
    { name: string; url: string } | undefined
  >(undefined);
  const [connectOpen, setConnectOpen] = useState(false);
  const [sheetServer, setSheetServer] = useState<McpServer | null>(null);
  const [editToolsServer, setEditToolsServer] = useState<McpServer | null>(
    null
  );
  const [credentialServer, setCredentialServer] = useState<McpServer | null>(
    null
  );
  const [deleteTarget, setDeleteTarget] = useState<McpServer | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Back from a sign-in at an MCP server (the OAuth callback page).
  const router = useRouter();
  const connected = useSearchParams().get("connected");
  useEffect(() => {
    if (!connected) return;
    toast({ title: `Signed in to ${connected}` });
    router.replace("/mcp-servers");
  }, [connected, router, toast]);

  const fetchServers = useCallback(async () => {
    try {
      const data = await mcpService.getServers();
      setServers(data);
      setLitellmError(null);
    } catch (error) {
      const parsed = parseApiError(error);
      const status =
        error && typeof error === "object" && "response" in error
          ? (error as { response?: { status?: number } }).response?.status
          : undefined;
      if (status === 503) {
        setLitellmError(String(parsed.description));
      } else {
        toast(parsed);
      }
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    (async () => {
      await fetchServers();
    })();
  }, [fetchServers]);

  const updateRow = (server: McpServer) => {
    setServers((prev) => prev.map((s) => (s.id === server.id ? server : s)));
  };

  const openAdd = (initial?: { name: string; url: string }) => {
    setAddInitial(initial);
    setAddOpen(true);
  };

  const handleToggleEnabled = async (server: McpServer) => {
    try {
      const updated = await mcpService.updateServer(server.id, {
        enabled: !server.enabled,
      });
      updateRow(updated);
    } catch (error) {
      toast(parseApiError(error));
    }
  };

  const handleDisconnect = async (server: McpServer) => {
    try {
      updateRow(await mcpService.deleteOwnCredential(server.id));
    } catch (error) {
      toast(parseApiError(error));
    }
  };

  const handleRefresh = async (server: McpServer) => {
    try {
      const updated = await mcpService.refreshServer(server.id);
      updateRow(updated);
      toast({
        title: "Success",
        description: "Tools refreshed",
        variant: "success",
      });
    } catch (error) {
      toast(parseApiError(error));
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await mcpService.deleteServer(deleteTarget.id);
      setServers((prev) => prev.filter((s) => s.id !== deleteTarget.id));
      toast({
        title: "Success",
        description: "MCP server deleted",
        variant: "success",
      });
      setDeleteTarget(null);
      setSheetServer(null);
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setDeleting(false);
    }
  };

  if (loading || orgLoading) {
    return <TableSkeleton rows={4} columns={5} />;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Give your models tools. Add a remote MCP server once; every member can
          use it in Chat, in Langflow and from an IDE or SDK.
        </p>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => setConnectOpen(true)}
          >
            Connect a client
          </Button>
          {canAdd && !litellmError && servers.length > 0 && (
            <Button type="button" onClick={() => openAdd()}>
              Add MCP server
            </Button>
          )}
        </div>
      </div>

      {litellmError && (
        <p
          role="alert"
          className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
        >
          {litellmError}
        </p>
      )}

      {servers.length === 0 ? (
        <div className="flex justify-center">
          <div className="w-full max-w-md space-y-3 rounded-xl border p-6 text-center">
            <p className="font-medium">No MCP servers yet</p>
            {canAdd ? (
              !litellmError && (
                <>
                  <Button type="button" onClick={() => openAdd()}>
                    + Add MCP server
                  </Button>
                  <p className="text-sm text-muted-foreground">
                    Try one:{" "}
                    {TRY_ONE_LINKS.map((link, i) => (
                      <span key={link.name}>
                        {i > 0 && " · "}
                        <Button
                          type="button"
                          variant="link"
                          className="h-auto p-0"
                          onClick={() =>
                            openAdd({ name: link.name, url: link.url })
                          }
                        >
                          {link.label}
                        </Button>
                      </span>
                    ))}
                  </p>
                </>
              )
            ) : (
              <p className="text-sm text-muted-foreground">
                Viewers cannot use tools. Ask an organization admin for a role
                that can.
              </p>
            )}
          </div>
        </div>
      ) : (
        <Table>
          <TableCaption className="sr-only">MCP servers</TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>URL</TableHead>
              <TableHead>Tools</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Checked</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {servers.map((server) => {
              const status = statusLabel(server);
              return (
                <TableRow key={server.id} aria-label={server.name}>
                  <TableCell className="font-medium">
                    <Button
                      type="button"
                      variant="link"
                      className="h-auto p-0"
                      onClick={() => setSheetServer(server)}
                    >
                      {server.name}
                    </Button>
                    {server.scope && server.scope !== "organization" && (
                      <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                        {server.scope === "personal" ? "only me" : "platform"}
                      </span>
                    )}
                  </TableCell>
                  <TableCell>{hostAndPath(server.url)}</TableCell>
                  <TableCell>{toolsLabel(server)}</TableCell>
                  <TableCell>
                    <span
                      className={`rounded-full px-2 py-1 text-sm ${status.className}`}
                    >
                      {status.text}
                    </span>
                  </TableCell>
                  <TableCell>{relativeTime(server.checked_at)}</TableCell>
                  <TableCell>
                    <DropdownMenu modal={false}>
                      <DropdownMenuTrigger asChild>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          aria-label={`Actions for ${server.name}`}
                        >
                          <DotsHorizontalIcon />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem asChild>
                          <Link
                            href={`/chat?tools=${server.name}`}
                            prefetch={false}
                          >
                            Try in chat
                          </Link>
                        </DropdownMenuItem>
                        {(server.can_change ?? isAdmin) ? (
                          <>
                            <DropdownMenuItem
                              onSelect={() => handleRefresh(server)}
                            >
                              Refresh tools
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onSelect={() => setEditToolsServer(server)}
                            >
                              Edit tools
                            </DropdownMenuItem>
                            {/* An OAuth server has no credential to
                                change: each member signs in. */}
                            {!server.oauth && (
                              <DropdownMenuItem
                                onSelect={() => setCredentialServer(server)}
                              >
                                Change credential
                              </DropdownMenuItem>
                            )}
                            <DropdownMenuItem
                              onSelect={() => handleToggleEnabled(server)}
                            >
                              {server.enabled ? "Disable" : "Enable"}
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              variant="destructive"
                              onSelect={() => setDeleteTarget(server)}
                            >
                              Delete
                            </DropdownMenuItem>
                          </>
                        ) : (
                          <DropdownMenuItem
                            onSelect={() => setSheetServer(server)}
                          >
                            View tools
                          </DropdownMenuItem>
                        )}
                        {server.credential_mode === "per_user" && !isViewer && (
                          <>
                            <DropdownMenuItem
                              onSelect={() => setConnectServer(server)}
                            >
                              {server.oauth
                                ? server.my_credential === "set"
                                  ? "Sign in again"
                                  : "Sign in"
                                : server.my_credential === "set"
                                  ? "Replace my credential"
                                  : "Connect my credential"}
                            </DropdownMenuItem>
                            {server.my_credential === "set" && (
                              <DropdownMenuItem
                                onSelect={() => handleDisconnect(server)}
                              >
                                {server.oauth
                                  ? "Sign out of this server"
                                  : "Disconnect my credential"}
                              </DropdownMenuItem>
                            )}
                          </>
                        )}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}

      <ConnectCredentialDialog
        server={connectServer}
        onOpenChange={(open) => !open && setConnectServer(null)}
        onSaved={updateRow}
      />
      <AddMcpServerDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        initial={addInitial}
        scopes={addScopes}
        onCreated={(server) => {
          setServers((prev) => [...prev, server]);
          setAddOpen(false);
        }}
      />

      <ConnectClientDialog
        open={connectOpen}
        onOpenChange={setConnectOpen}
        servers={servers}
      />

      <McpServerSheet
        server={sheetServer}
        open={sheetServer !== null}
        onOpenChange={(open) => !open && setSheetServer(null)}
        admin={sheetServer?.can_change ?? isAdmin}
        onRequestDelete={(server) => {
          setSheetServer(null);
          setDeleteTarget(server);
        }}
      />

      <EditToolsDialog
        server={editToolsServer}
        open={editToolsServer !== null}
        onOpenChange={(open) => !open && setEditToolsServer(null)}
        onUpdated={(server) => {
          updateRow(server);
          setEditToolsServer(null);
        }}
      />

      <ChangeCredentialDialog
        server={credentialServer}
        open={credentialServer !== null}
        onOpenChange={(open) => !open && setCredentialServer(null)}
        onUpdated={(server) => {
          updateRow(server);
          setCredentialServer(null);
        }}
      />

      <Dialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && !deleting && setDeleteTarget(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm Deletion</DialogTitle>
            <DialogDescription>
              Delete &quot;{deleteTarget?.name}&quot;? Chats and flows that use
              these tools stop working.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setDeleteTarget(null)}
              disabled={deleting}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={handleDelete}
              loading={deleting}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
