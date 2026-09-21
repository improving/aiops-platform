"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";
import { useRuntimeConfig } from "@/lib/runtimeConfig";
import { mcpService } from "@/services/mcpService";
import type {
  McpApproval,
  McpCatalogEntry,
  McpRegistryPreview,
  McpServer,
} from "@/types/mcp";
import { SCOPE_LABEL } from "@/types/mcp";
import { ApprovalField } from "@/components/mcp/ApprovalField";
import { CatalogReviewDialog } from "@/components/mcp/CatalogReviewDialog";
import {
  SettingsFields,
  missingSettings,
} from "@/components/mcp/SettingsFields";

const NAME_RE = /^[a-z][a-z0-9_]{0,30}[a-z0-9]$|^[a-z]$/;

const REACHES: Record<string, string> = {
  none: "reaches nothing",
  public: "reaches the internet",
  cluster: "reaches your cluster and the internet",
};

/**
 * Deploy an MCP server from the catalog (W12): choose an entry, fill its
 * settings, Deploy. The dialog closes at once; the row then shows the
 * server starting. There is no tool list to pick from yet: the tools are
 * listed when the server runs, and "Edit tools" limits them then.
 *
 * A platform admin also sees drafts here, imports an image entry of the
 * MCP registry as a draft, and reviews and publishes it.
 */
export type DeployScope = "organization" | "platform";

export function DeployMcpServerDialog({
  open,
  onOpenChange,
  onDeployed,
  isPlatformAdmin,
  scopes,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeployed: (server: McpServer) => void;
  isPlatformAdmin: boolean;
  /** Who the caller may deploy for: the organization (its admin), the
      platform (a platform admin). Never one member: a deployed server
      has no credential of its own, and every key of the organization
      reaches it in the proxy. */
  scopes: DeployScope[];
}) {
  const { toast } = useToast();
  const { mcpRegistry } = useRuntimeConfig();
  const [catalog, setCatalog] = useState<McpCatalogEntry[] | null>(null);
  const [entry, setEntry] = useState<McpCatalogEntry | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [approval, setApproval] = useState<McpApproval>("writes");
  const [scope, setScope] = useState<DeployScope>(scopes[0] ?? "organization");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewId, setReviewId] = useState<string | null>(null);
  // Import, for a platform admin.
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<McpRegistryPreview[] | null>(null);
  const [searching, setSearching] = useState(false);

  const loadCatalog = useCallback(async () => {
    try {
      setCatalog(await mcpService.getCatalog());
    } catch (e) {
      setError(String(parseApiError(e).description));
      setCatalog([]);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    (async () => {
      await loadCatalog();
    })();
  }, [open, loadCatalog]);

  const close = (next: boolean) => {
    if (!next) {
      setEntry(null);
      setName("");
      setDescription("");
      setValues({});
      setApproval("writes");
      setScope(scopes[0] ?? "organization");
      setError(null);
      setQuery("");
      setFound(null);
    }
    onOpenChange(next);
  };

  const choose = (chosen: McpCatalogEntry) => {
    setEntry(chosen);
    setName(chosen.name);
    setValues({});
    setError(null);
  };

  const search = async () => {
    setSearching(true);
    setError(null);
    try {
      const all = await mcpService.searchRegistry(query.trim());
      setFound(all.filter((e) => e.deployable || e.deployable_reason));
    } catch (e) {
      setError(String(parseApiError(e).description));
    } finally {
      setSearching(false);
    }
  };

  const importEntry = async (preview: McpRegistryPreview) => {
    setError(null);
    try {
      const draft = await mcpService.importCatalogEntry(preview.name);
      await loadCatalog();
      setFound(null);
      setReviewId(draft.id);
    } catch (e) {
      setError(String(parseApiError(e).description));
    }
  };

  const deploy = async () => {
    if (!entry) return;
    setSaving(true);
    setError(null);
    try {
      const server = await mcpService.deploy({
        catalog: entry.name,
        name,
        description: description.trim() || undefined,
        settings: values,
        approval,
        scope,
      });
      toast({
        title: "Success",
        description: `${name} is starting`,
        variant: "success",
      });
      onDeployed(server);
      close(false);
    } catch (e) {
      setError(String(parseApiError(e).description));
    } finally {
      setSaving(false);
    }
  };

  const nameValid = NAME_RE.test(name);
  const missing = entry ? missingSettings(entry.settings, values) : [];

  return (
    <>
      <Dialog open={open} onOpenChange={close}>
        <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Deploy an MCP server</DialogTitle>
            <DialogDescription>
              {entry ? "Step 2 of 2: Settings" : "Step 1 of 2: Choose"}
            </DialogDescription>
          </DialogHeader>

          {!entry ? (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                The platform runs the server in your cluster. Only the
                platform&apos;s proxy can call it, and every member uses its
                tools in Chat, in Langflow and from an IDE.
              </p>
              <ul aria-label="Catalog" className="grid gap-3 sm:grid-cols-2">
                {(catalog ?? []).map((item) => (
                  <li key={item.id} className="rounded-lg border p-3">
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-medium">{item.title}</p>
                      {item.status !== "published" && (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
                          {item.status}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 line-clamp-3 text-xs text-muted-foreground">
                      {item.description}
                    </p>
                    <p className="mt-2 text-xs text-muted-foreground">
                      {REACHES[item.egress]}
                      {item.docs_url && (
                        <>
                          {" · "}
                          <a
                            href={item.docs_url}
                            target="_blank"
                            rel="noreferrer"
                            className="underline"
                          >
                            Docs
                          </a>
                        </>
                      )}
                    </p>
                    <div className="mt-3 flex gap-2">
                      {item.status === "published" && (
                        <Button
                          type="button"
                          size="sm"
                          aria-label={`Choose ${item.title}`}
                          onClick={() => choose(item)}
                        >
                          Choose
                        </Button>
                      )}
                      {isPlatformAdmin && item.source !== "builtin" && (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          aria-label={`Review ${item.title}`}
                          onClick={() => setReviewId(item.id)}
                        >
                          Review
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
              {catalog !== null && catalog.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  The catalog is empty.
                </p>
              )}

              {isPlatformAdmin && mcpRegistry && (
                <div className="space-y-2 rounded-lg border border-dashed p-3">
                  <p className="text-sm font-medium">
                    Import from the MCP registry
                  </p>
                  <p className="text-xs text-muted-foreground">
                    An entry with a container image that speaks streamable HTTP
                    becomes a draft. Nobody can deploy it until you have
                    reviewed and published it.
                  </p>
                  <form
                    className="flex items-end gap-2"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void search();
                    }}
                  >
                    <div className="flex-1 space-y-1">
                      <Label htmlFor="mcp-catalog-query">
                        Search images in the registry
                      </Label>
                      <Input
                        id="mcp-catalog-query"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                      />
                    </div>
                    <Button type="submit" variant="outline" loading={searching}>
                      Search
                    </Button>
                  </form>
                  {found !== null && (
                    <ul aria-label="Registry images" className="space-y-2">
                      {found.length === 0 && (
                        <li className="text-xs text-muted-foreground">
                          No entry with a package found.
                        </li>
                      )}
                      {found.map((preview) => (
                        <li
                          key={preview.name}
                          className="flex items-start justify-between gap-3 text-sm"
                        >
                          <div className="min-w-0">
                            <p className="truncate">{preview.name}</p>
                            {!preview.deployable && (
                              <p className="text-xs text-muted-foreground">
                                Not deployable: {preview.deployable_reason}
                              </p>
                            )}
                          </div>
                          {preview.deployable && (
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              aria-label={`Import ${preview.name}`}
                              disabled={preview.already_imported}
                              onClick={() => importEntry(preview)}
                            >
                              {preview.already_imported
                                ? "Imported"
                                : "Import as draft"}
                            </Button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              {error && (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                {entry.title} · {entry.image}
              </p>
              <div className="space-y-1">
                <Label htmlFor="mcp-deploy-name">Name</Label>
                <Input
                  id="mcp-deploy-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Lower case, used as the prefix of the tool names.
                </p>
                {name !== "" && !nameValid && (
                  <p className="text-xs text-destructive">
                    Lower case letters, digits and _; starts with a letter.
                  </p>
                )}
              </div>
              <div className="space-y-1">
                <Label htmlFor="mcp-deploy-description">Description</Label>
                <Input
                  id="mcp-deploy-description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>
              <SettingsFields
                idPrefix="mcp-deploy"
                schema={entry.settings}
                values={values}
                onChange={(key, value) =>
                  setValues((current) => ({ ...current, [key]: value }))
                }
              />
              {scopes.length > 1 && (
                <fieldset className="space-y-2">
                  <legend className="text-sm font-medium">
                    Who can use it
                  </legend>
                  {scopes.map((value) => (
                    <div key={value} className="flex items-center gap-2">
                      <input
                        type="radio"
                        id={`mcp-deploy-scope-${value}`}
                        name="mcp-deploy-scope"
                        checked={scope === value}
                        onChange={() => setScope(value)}
                      />
                      <Label htmlFor={`mcp-deploy-scope-${value}`}>
                        {SCOPE_LABEL[value]}
                      </Label>
                    </div>
                  ))}
                </fieldset>
              )}
              {scopes.length === 1 && scope === "platform" && (
                <p className="text-xs text-muted-foreground">
                  Every organization of the platform can use this server.
                </p>
              )}
              {entry.settings.some((s) => s.secret) && (
                <p className="text-xs text-muted-foreground">
                  {scope === "platform"
                    ? "The model of every member of every organization acts with these credentials through the tools."
                    : "Every member\u2019s model acts with these credentials through the tools."}
                </p>
              )}
              <ApprovalField
                idPrefix="mcp-deploy"
                value={approval}
                onChange={setApproval}
              />
              <p className="text-xs text-muted-foreground">
                The tools are listed when the server runs; limit them then with
                Edit tools.
              </p>
              {error && (
                <p role="alert" className="text-sm text-destructive">
                  {error}
                </p>
              )}
            </div>
          )}

          <DialogFooter>
            {entry ? (
              <>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setEntry(null);
                    setError(null);
                  }}
                >
                  Back
                </Button>
                <Button
                  type="button"
                  onClick={deploy}
                  disabled={!nameValid || missing.length > 0 || saving}
                  loading={saving}
                >
                  Deploy
                </Button>
              </>
            ) : (
              <Button
                type="button"
                variant="outline"
                onClick={() => close(false)}
              >
                Cancel
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <CatalogReviewDialog
        entryId={reviewId}
        onOpenChange={(next) => {
          if (!next) setReviewId(null);
        }}
        onChanged={loadCatalog}
      />
    </>
  );
}
