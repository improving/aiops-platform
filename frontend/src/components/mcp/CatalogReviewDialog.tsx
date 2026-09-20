"use client";

import { useEffect, useState } from "react";
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
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";
import { mcpService } from "@/services/mcpService";
import type { McpCatalogReview, McpEgress } from "@/types/mcp";

const EGRESS: { value: McpEgress; label: string }[] = [
  { value: "none", label: "Nothing" },
  { value: "public", label: "The internet (port 443)" },
  {
    value: "cluster",
    label: "The internet, and the cluster and the site (every private address)",
  },
];

/**
 * A platform admin's review of an imported catalog entry: what would
 * run (the image, its arguments, its endpoint), what an admin fills,
 * and what the pod may reach. Nobody can deploy a draft; Publish is the
 * only way to a deployable image, also after a sync changed it.
 */
export function CatalogReviewDialog({
  entryId,
  onOpenChange,
  onChanged,
}: {
  /** null closes the dialog. */
  entryId: string | null;
  onOpenChange: (open: boolean) => void;
  onChanged: () => void | Promise<void>;
}) {
  const { toast } = useToast();
  const [entry, setEntry] = useState<McpCatalogReview | null>(null);
  const [title, setTitle] = useState("");
  const [args, setArgs] = useState("");
  const [port, setPort] = useState("");
  const [path, setPath] = useState("");
  const [egress, setEgress] = useState<McpEgress>("public");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const show = (loaded: McpCatalogReview) => {
    setEntry(loaded);
    setTitle(loaded.title);
    setArgs(loaded.args.join("\n"));
    setPort(String(loaded.port));
    setPath(loaded.path);
    setEgress(loaded.egress);
  };

  useEffect(() => {
    if (!entryId) return;
    (async () => {
      setError(null);
      try {
        show(await mcpService.getCatalogEntry(entryId));
      } catch (e) {
        setError(String(parseApiError(e).description));
      }
    })();
  }, [entryId]);

  const run = async (
    work: () => Promise<McpCatalogReview | void>,
    done: string,
    closeAfter = false
  ) => {
    setBusy(true);
    setError(null);
    try {
      const changed = await work();
      if (changed) show(changed);
      await onChanged();
      toast({ title: "Success", description: done, variant: "success" });
      if (closeAfter) onOpenChange(false);
    } catch (e) {
      setError(String(parseApiError(e).description));
    } finally {
      setBusy(false);
    }
  };

  const changes = (status?: McpCatalogReview["status"]) => ({
    title: title.trim(),
    args: args
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean),
    port: Number(port),
    path: path.trim(),
    egress,
    ...(status ? { status } : {}),
  });

  return (
    <Dialog
      open={entryId !== null}
      onOpenChange={(next) => {
        if (!next) setEntry(null);
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Review {entry?.title ?? "the entry"}</DialogTitle>
          <DialogDescription>
            {entry
              ? `${entry.source_id}${entry.source_version ? ` · ${entry.source_version}` : ""} · ${entry.status}`
              : "Loading the entry"}
          </DialogDescription>
        </DialogHeader>

        {entry && (
          <div className="space-y-4">
            <div className="rounded-md border p-3 text-sm">
              <p className="font-medium">What would run</p>
              <p className="mt-1 break-all font-mono text-xs">
                {entry.image}
                {entry.tag.startsWith("@") ? entry.tag : `:${entry.tag}`}
              </p>
              <p className="mt-2 text-xs text-muted-foreground">
                As a non-root user with a read-only file system, no capabilities
                and no identity in the cluster. Only the platform&apos;s proxy
                can call it.
              </p>
            </div>

            {entry.notes.length > 0 && (
              <ul
                aria-label="Notes of the import"
                className="list-disc space-y-1 rounded-md border border-amber-300 bg-amber-50 p-3 pl-6 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
              >
                {entry.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            )}

            <div className="space-y-1">
              <Label htmlFor="mcp-review-title">Title</Label>
              <Input
                id="mcp-review-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="mcp-review-args">
                Arguments (one on each line)
              </Label>
              <Textarea
                id="mcp-review-args"
                rows={5}
                className="font-mono text-xs"
                value={args}
                onChange={(e) => setArgs(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                {"{host}"}, {"{port}"} and {"{path}"} are filled by the
                platform.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label htmlFor="mcp-review-port">Port</Label>
                <Input
                  id="mcp-review-port"
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="mcp-review-path">Path</Label>
                <Input
                  id="mcp-review-path"
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                />
              </div>
            </div>

            <div className="space-y-1 text-sm">
              <p className="font-medium">
                Settings an admin fills ({entry.settings.length})
              </p>
              <ul className="space-y-0.5 text-xs text-muted-foreground">
                {entry.settings.map((s) => (
                  <li key={s.name}>
                    <span className="font-mono">{s.name}</span>
                    {s.secret ? " · secret" : ""}
                    {s.required ? " · required" : ""}
                    {s.default ? ` · default ${s.default}` : ""}
                  </li>
                ))}
              </ul>
            </div>

            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">
                What the server may reach
              </legend>
              {EGRESS.map((option) => (
                <div key={option.value} className="flex items-start gap-2">
                  <input
                    type="radio"
                    className="mt-1"
                    id={`mcp-review-egress-${option.value}`}
                    name="mcp-review-egress"
                    checked={egress === option.value}
                    onChange={() => setEgress(option.value)}
                  />
                  <Label htmlFor={`mcp-review-egress-${option.value}`}>
                    {option.label}
                  </Label>
                </div>
              ))}
            </fieldset>

            {entry.in_use > 0 && (
              <p className="text-xs text-muted-foreground">
                {entry.in_use} deployed server(s) use this entry. They keep
                their image until an admin upgrades them.
              </p>
            )}
          </div>
        )}

        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        <DialogFooter className="gap-2 sm:justify-between">
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!entry || busy}
              onClick={() =>
                run(
                  () => mcpService.syncCatalogEntry(entry!.id),
                  "Read again from the registry"
                )
              }
            >
              Sync
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={!entry || busy || (entry?.in_use ?? 0) > 0}
              onClick={() =>
                run(
                  () => mcpService.deleteCatalogEntry(entry!.id),
                  "Entry removed",
                  true
                )
              }
            >
              Remove
            </Button>
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!entry || busy}
              onClick={() =>
                run(
                  () => mcpService.updateCatalogEntry(entry!.id, changes()),
                  "Saved"
                )
              }
            >
              Save
            </Button>
            {entry?.status === "published" ? (
              <Button
                type="button"
                disabled={busy}
                onClick={() =>
                  run(
                    () =>
                      mcpService.updateCatalogEntry(
                        entry.id,
                        changes("deprecated")
                      ),
                    "Deprecated: no new deploys",
                    true
                  )
                }
              >
                Deprecate
              </Button>
            ) : (
              <Button
                type="button"
                disabled={!entry || busy}
                onClick={() =>
                  run(
                    () =>
                      mcpService.updateCatalogEntry(
                        entry!.id,
                        changes("published")
                      ),
                    "Published: organization admins can deploy it",
                    true
                  )
                }
              >
                Publish
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
