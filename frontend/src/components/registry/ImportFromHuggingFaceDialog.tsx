"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/hooks/use-toast";
import { registryService } from "@/services/registryService";
import { parseApiError } from "@/lib/utils";
import type { Model, RegistryEntryPreview } from "@/types/models";

interface ImportFromHuggingFaceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: (model: Model) => void;
}

export default function ImportFromHuggingFaceDialog({
  open,
  onOpenChange,
  onImported,
}: ImportFromHuggingFaceDialogProps) {
  const { toast } = useToast();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<RegistryEntryPreview[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [importingId, setImportingId] = useState<string | null>(null);

  const reset = () => {
    setQuery("");
    setResults(null);
  };

  const close = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const handleSearch = async () => {
    setSearching(true);
    try {
      const entries = await registryService.search("huggingface", query);
      setResults(entries);
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setSearching(false);
    }
  };

  const handleImport = async (entry: RegistryEntryPreview) => {
    setImportingId(entry.source_id);
    try {
      const model = await registryService.importEntry({
        source: "huggingface",
        source_id: entry.source_id,
        status: "draft",
      });
      toast({
        title: "Success",
        description: `Imported "${entry.name}" as a draft`,
        variant: "success",
      });
      onImported(model);
      setResults(
        (prev) =>
          prev?.map((r) =>
            r.source_id === entry.source_id
              ? { ...r, already_imported: true }
              : r
          ) ?? null
      );
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setImportingId(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Import from Hugging Face</DialogTitle>
          <DialogDescription>
            Search the Hugging Face Hub and import a repo as a draft entry.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="flex gap-2">
            <Input
              type="search"
              aria-label="Search Hugging Face"
              placeholder="e.g. Qwen/Qwen3-0.6B-GGUF"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleSearch();
                }
              }}
            />
            <Button
              type="button"
              onClick={handleSearch}
              loading={searching}
              disabled={searching}
            >
              Search
            </Button>
          </div>
          {results && (
            <div className="max-h-80 space-y-2 overflow-y-auto">
              {results.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No results found.
                </p>
              ) : (
                results.map((entry) => (
                  <div
                    key={entry.source_id}
                    data-testid="hf-result"
                    className="flex items-center justify-between rounded-md border p-3"
                  >
                    <div>
                      <p className="font-medium">{entry.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {entry.category ?? "unknown"}
                        {entry.license ? ` · ${entry.license}` : ""}
                        {entry.size
                          ? ` · ${(entry.size / (1024 * 1024)).toFixed(0)} MB`
                          : ""}
                      </p>
                      {entry.tags.includes("gated") && (
                        <p className="text-xs text-yellow-700">
                          Gated repo: no serving options
                        </p>
                      )}
                    </div>
                    <Button
                      type="button"
                      size="sm"
                      disabled={
                        entry.already_imported ||
                        importingId === entry.source_id
                      }
                      loading={importingId === entry.source_id}
                      onClick={() => handleImport(entry)}
                    >
                      {entry.already_imported
                        ? "Already imported"
                        : "Import as draft"}
                    </Button>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)}>
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
