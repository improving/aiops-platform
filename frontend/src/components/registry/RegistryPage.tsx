"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError, formatEnumLabel } from "@/lib/utils";
import { registryService } from "@/services/registryService";
import type { Model } from "@/types/models";
import { DeleteButton } from "@/components/DeleteButton";
import ImportFromHuggingFaceDialog from "@/components/registry/ImportFromHuggingFaceDialog";
import AddOllamaModelDialog from "@/components/registry/AddOllamaModelDialog";
import AddHostedModelDialog from "@/components/registry/AddHostedModelDialog";
import AddManuallyDialog from "@/components/registry/AddManuallyDialog";
import EditEntryDialog from "@/components/registry/EditEntryDialog";
import { TableSkeleton } from "@/components/LoadingState";

const STATUS_BADGE: Record<string, string> = {
  draft: "bg-gray-100 text-gray-800",
  published: "bg-green-100 text-green-800",
  deprecated: "bg-red-100 text-red-800",
};

interface RegistryPageProps {
  /**
   * Whether the caller may import, publish, sync, edit or delete entries.
   * Resolved by the route (app/models/registry/page.tsx), the one place
   * that decides whether it is even safe to call useSession() -- a UI
   * hint only, like session.roles itself, since the backend enforces
   * require_admin regardless.
   */
  admin: boolean;
}

export default function RegistryPage({ admin }: RegistryPageProps) {
  const { toast } = useToast();
  const [entries, setEntries] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);
  const [source, setSource] = useState("all");
  const [capability, setCapability] = useState("all");
  const [status, setStatus] = useState("all");
  const [importHfOpen, setImportHfOpen] = useState(false);
  const [addOllamaOpen, setAddOllamaOpen] = useState(false);
  const [addHostedOpen, setAddHostedOpen] = useState(false);
  const [addManuallyOpen, setAddManuallyOpen] = useState(false);
  const [editing, setEditing] = useState<Model | null>(null);

  const fetchEntries = useCallback(async () => {
    try {
      const data = await registryService.listEntries({
        source: source === "all" ? undefined : source,
        capability: capability === "all" ? undefined : capability,
        status: admin && status !== "all" ? status : undefined,
      });
      setEntries(data);
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setLoading(false);
    }
  }, [source, capability, status, admin, toast]);

  useEffect(() => {
    fetchEntries();
  }, [fetchEntries]);

  const upsert = (model: Model) => {
    setEntries((prev) => {
      const exists = prev.some((m) => m.id === model.id);
      return exists
        ? prev.map((m) => (m.id === model.id ? model : m))
        : [...prev, model];
    });
  };

  const handlePublishToggle = async (model: Model) => {
    try {
      const next = model.status === "published" ? "deprecated" : "published";
      const updated = await registryService.update(model.id, {
        status: next,
      });
      upsert(updated);
    } catch (error) {
      toast(parseApiError(error));
    }
  };

  const handleSync = async (model: Model) => {
    try {
      const updated = await registryService.sync(model.id);
      upsert(updated);
      toast({ title: "Success", description: "Entry synced" });
    } catch (error) {
      toast(parseApiError(error));
    }
  };

  const handleDelete = async (id: string) => {
    await registryService.remove(id);
    setEntries((prev) => prev.filter((m) => m.id !== id));
  };

  if (loading) {
    return <TableSkeleton rows={6} columns={5} />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap gap-4">
          <Select value={source} onValueChange={setSource}>
            <SelectTrigger className="w-[180px]" aria-label="Source">
              <SelectValue placeholder="All Sources" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Sources</SelectItem>
              <SelectItem value="manual">Manual</SelectItem>
              <SelectItem value="huggingface">Hugging Face</SelectItem>
              <SelectItem value="ollama">Ollama</SelectItem>
              <SelectItem value="openrouter">OpenRouter</SelectItem>
            </SelectContent>
          </Select>
          <Select value={capability} onValueChange={setCapability}>
            <SelectTrigger className="w-[180px]" aria-label="Capability">
              <SelectValue placeholder="All Capabilities" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Capabilities</SelectItem>
              <SelectItem value="chat">Chat</SelectItem>
              <SelectItem value="embedding">Embedding</SelectItem>
              <SelectItem value="rerank">Rerank</SelectItem>
              <SelectItem value="guard">Guard</SelectItem>
            </SelectContent>
          </Select>
          {admin && (
            <Select value={status} onValueChange={setStatus}>
              <SelectTrigger className="w-[180px]" aria-label="Status">
                <SelectValue placeholder="All Statuses" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Statuses</SelectItem>
                <SelectItem value="draft">Draft</SelectItem>
                <SelectItem value="published">Published</SelectItem>
                <SelectItem value="deprecated">Deprecated</SelectItem>
              </SelectContent>
            </Select>
          )}
        </div>
        {admin ? (
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => setImportHfOpen(true)}>
              Import from Hugging Face
            </Button>
            <Button variant="outline" onClick={() => setAddOllamaOpen(true)}>
              Add Ollama model
            </Button>
            <Button variant="outline" onClick={() => setAddHostedOpen(true)}>
              Add hosted model
            </Button>
            <Button onClick={() => setAddManuallyOpen(true)}>
              Add manually
            </Button>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Only organization admins can import or change registry entries.
          </p>
        )}
      </div>

      {entries.length === 0 ? (
        <p className="text-muted-foreground">No registry entries yet.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Source</TableHead>
              <TableHead>License</TableHead>
              <TableHead>Formats</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Serving options</TableHead>
              {admin && <TableHead />}
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((model) => (
              <TableRow key={model.id} aria-label={model.name}>
                <TableCell className="font-medium">{model.name}</TableCell>
                <TableCell>
                  <span className="rounded-full bg-blue-100 px-2 py-1 text-sm text-blue-800">
                    {model.source ?? "manual"}
                  </span>
                </TableCell>
                <TableCell>{model.license ?? "—"}</TableCell>
                <TableCell>{(model.formats ?? []).join(", ") || "—"}</TableCell>
                <TableCell>
                  <span
                    className={`rounded-full px-2 py-1 text-sm ${
                      STATUS_BADGE[model.status ?? "published"] ??
                      "bg-gray-100 text-gray-800"
                    }`}
                  >
                    {formatEnumLabel(model.status ?? "published")}
                  </span>
                </TableCell>
                <TableCell>
                  {(model.serving_options ?? []).length === 0
                    ? "—"
                    : (model.serving_options ?? [])
                        .map((o) => `${o.engine}: ${o.reference}`)
                        .join(", ")}
                </TableCell>
                {admin && (
                  <TableCell>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handlePublishToggle(model)}
                      >
                        {model.status === "published" ? "Deprecate" : "Publish"}
                      </Button>
                      {model.source_id && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleSync(model)}
                        >
                          Sync
                        </Button>
                      )}
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setEditing(model)}
                      >
                        Edit
                      </Button>
                      <DeleteButton
                        buttonText="Delete entry"
                        modalDescription={`Delete "${model.name}" from the registry? This cannot be undone.`}
                        onDelete={() => handleDelete(model.id)}
                        successToastMessage="Entry deleted"
                      />
                    </div>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {admin && (
        <>
          <ImportFromHuggingFaceDialog
            open={importHfOpen}
            onOpenChange={setImportHfOpen}
            onImported={upsert}
          />
          <AddOllamaModelDialog
            open={addOllamaOpen}
            onOpenChange={setAddOllamaOpen}
            onImported={upsert}
          />
          <AddHostedModelDialog
            open={addHostedOpen}
            onOpenChange={setAddHostedOpen}
            onImported={upsert}
          />
          <AddManuallyDialog
            open={addManuallyOpen}
            onOpenChange={setAddManuallyOpen}
            onCreated={upsert}
          />
          <EditEntryDialog
            model={editing}
            onOpenChange={(open) => {
              if (!open) setEditing(null);
            }}
            onUpdated={(model) => {
              upsert(model);
              setEditing(null);
            }}
          />
        </>
      )}
    </div>
  );
}
