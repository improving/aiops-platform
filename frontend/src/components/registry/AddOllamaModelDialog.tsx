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

interface AddOllamaModelDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: (model: Model) => void;
}

export default function AddOllamaModelDialog({
  open,
  onOpenChange,
  onImported,
}: AddOllamaModelDialogProps) {
  const { toast } = useToast();
  const [tag, setTag] = useState("");
  const [preview, setPreview] = useState<RegistryEntryPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [importing, setImporting] = useState(false);

  const reset = () => {
    setTag("");
    setPreview(null);
  };

  const close = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const handlePreview = async () => {
    setPreviewing(true);
    setPreview(null);
    try {
      const [entry] = await registryService.search("ollama", tag, 1);
      setPreview(entry ?? null);
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setPreviewing(false);
    }
  };

  const handleImport = async () => {
    if (!preview) return;
    setImporting(true);
    try {
      const model = await registryService.importEntry({
        source: "ollama",
        source_id: preview.source_id,
        status: "draft",
      });
      toast({
        title: "Success",
        description: `Imported "${preview.name}" as a draft`,
        variant: "success",
      });
      onImported(model);
      close(false);
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setImporting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add Ollama model</DialogTitle>
          <DialogDescription>
            Ollama has no search endpoint: enter the exact tag (e.g. qwen3:0.6b)
            and preview its manifest.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="flex gap-2">
            <Input
              aria-label="Ollama tag"
              placeholder="qwen3:0.6b"
              value={tag}
              onChange={(e) => setTag(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handlePreview();
                }
              }}
            />
            <Button
              type="button"
              onClick={handlePreview}
              disabled={!tag || previewing}
              loading={previewing}
            >
              Preview
            </Button>
          </div>
          {preview && (
            <div className="rounded-md border p-3">
              <p className="font-medium">{preview.name}</p>
              <p className="text-xs text-muted-foreground">
                {preview.size
                  ? `${(preview.size / (1024 * 1024)).toFixed(0)} MB`
                  : "size unknown"}
                {preview.capabilities.length
                  ? ` · ${preview.capabilities.join(", ")}`
                  : ""}
              </p>
              {preview.already_imported && (
                <p className="text-xs text-yellow-700">Already imported</p>
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleImport}
            disabled={!preview || preview.already_imported || importing}
            loading={importing}
          >
            Import as draft
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
