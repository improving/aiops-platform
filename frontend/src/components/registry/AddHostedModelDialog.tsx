"use client";

import { useEffect, useState } from "react";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/hooks/use-toast";
import { registryService } from "@/services/registryService";
import { providerService } from "@/services/providerService";
import { parseApiError } from "@/lib/utils";
import type { Model, Provider, RegistryEntryPreview } from "@/types/models";

interface AddHostedModelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: (model: Model) => void;
}

export default function AddHostedModelDialog({
  open,
  onOpenChange,
  onImported,
}: AddHostedModelDialogProps) {
  const { toast } = useToast();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providerId, setProviderId] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<RegistryEntryPreview[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [importingId, setImportingId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    providerService
      .getProviders()
      .then((data) =>
        setProviders(data.filter((p) => p.kind === "openrouter" && p.enabled))
      )
      .catch((error) => toast(parseApiError(error)));
  }, [open, toast]);

  const reset = () => {
    setProviderId("");
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
      const entries = await registryService.search("openrouter", query);
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
        source: "openrouter",
        source_id: entry.source_id,
        provider_id: providerId,
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
          <DialogTitle>Add hosted model</DialogTitle>
          <DialogDescription>
            Search OpenRouter and register a model under one of your enabled
            OpenRouter providers.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {providers.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No enabled OpenRouter provider yet. Add one on the Providers page
              first.
            </p>
          ) : (
            <>
              <Select value={providerId} onValueChange={setProviderId}>
                <SelectTrigger aria-label="Provider">
                  <SelectValue placeholder="Select a provider" />
                </SelectTrigger>
                <SelectContent>
                  {providers.map((provider) => (
                    <SelectItem key={provider.id} value={provider.id}>
                      {provider.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="flex gap-2">
                <Input
                  type="search"
                  aria-label="Search OpenRouter"
                  placeholder="Search by model id or name"
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
                        className="flex items-center justify-between rounded-md border p-3"
                      >
                        <div>
                          <p className="font-medium">{entry.name}</p>
                          <p className="text-xs text-muted-foreground">
                            {entry.source_id}
                            {entry.context_length
                              ? ` · ${entry.context_length} ctx`
                              : ""}
                          </p>
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          disabled={
                            !providerId ||
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
            </>
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
