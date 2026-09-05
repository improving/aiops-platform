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
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";
import { providerService } from "@/services/providerService";
import type { DiscoveredModel, Provider } from "@/types/models";

// Mirrors backend/utils/providers.py PROVIDER_KINDS; there is no endpoint
// that lists them.
const PROVIDER_KINDS = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "gemini", label: "Google Gemini" },
  { value: "groq", label: "Groq" },
  { value: "openrouter", label: "OpenRouter" },
];

interface AddProviderDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (provider: Provider) => void;
}

export function AddProviderDialog({
  open,
  onOpenChange,
  onCreated,
}: AddProviderDialogProps) {
  const { toast } = useToast();
  const [kind, setKind] = useState("");
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [discovered, setDiscovered] = useState<DiscoveredModel[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [discovering, setDiscovering] = useState(false);
  const [saving, setSaving] = useState(false);

  const reset = () => {
    setKind("");
    setName("");
    setBaseUrl("");
    setApiKey("");
    setDiscovered(null);
    setSelected(new Set());
  };

  const close = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const canDiscover = !!kind && !!apiKey && !discovering;
  const canSave = !!kind && !!name && !!apiKey && !saving;

  const handleDiscover = async () => {
    setDiscovering(true);
    try {
      const models = await providerService.discoverModels({
        kind,
        api_key: apiKey,
        base_url: baseUrl || undefined,
      });
      setDiscovered(models);
      setSelected(new Set(models.map((m) => m.id)));
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setDiscovering(false);
    }
  };

  const toggleModel = (id: string, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const models = Array.from(selected);
      const displayNames = Object.fromEntries(
        (discovered ?? [])
          .filter((m) => selected.has(m.id))
          .map((m) => [m.id, m.display_name])
      );
      const provider = await providerService.createProvider({
        kind,
        name,
        base_url: baseUrl || undefined,
        api_key: apiKey,
        models,
        display_names: displayNames,
      });
      toast({
        title: "Success",
        description: `Provider "${provider.name}" added`,
        variant: "success",
      });
      onCreated(provider);
      reset();
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add provider</DialogTitle>
          <DialogDescription>
            The API key is stored in a Secret and never shown again.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="provider-kind">Kind</Label>
            <Select value={kind} onValueChange={setKind}>
              <SelectTrigger id="provider-kind" aria-label="Kind">
                <SelectValue placeholder="Select a provider" />
              </SelectTrigger>
              <SelectContent>
                {PROVIDER_KINDS.map((k) => (
                  <SelectItem key={k.value} value={k.value}>
                    {k.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="provider-name">Name</Label>
            <Input
              id="provider-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="provider-base-url">Base URL (optional)</Label>
            <Input
              id="provider-base-url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.example.com/v1"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="provider-api-key">API key</Label>
            <Input
              id="provider-api-key"
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={handleDiscover}
            disabled={!canDiscover}
            loading={discovering}
          >
            Discover models
          </Button>
          {discovered && (
            <div className="max-h-64 space-y-2 overflow-y-auto rounded-md border p-3">
              {discovered.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No models found.
                </p>
              ) : (
                discovered.map((model) => (
                  <div key={model.id} className="flex items-center space-x-2">
                    <Checkbox
                      id={`provider-model-${model.id}`}
                      checked={selected.has(model.id)}
                      onCheckedChange={(checked) =>
                        toggleModel(model.id, checked as boolean)
                      }
                    />
                    <Label htmlFor={`provider-model-${model.id}`}>
                      {model.id}
                    </Label>
                    <span className="text-xs text-muted-foreground">
                      {model.capability}
                      {model.context_length
                        ? ` · ${model.context_length} ctx`
                        : ""}
                    </span>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={!canSave} loading={saving}>
            Save provider
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
