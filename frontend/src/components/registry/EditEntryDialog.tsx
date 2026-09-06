"use client";

import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { TrashIcon } from "@radix-ui/react-icons";
import { useToast } from "@/components/hooks/use-toast";
import { modelService } from "@/services/modelService";
import { registryService } from "@/services/registryService";
import { parseApiError } from "@/lib/utils";
import type { Model } from "@/types/models";

interface ServingOptionRow {
  engine: string;
  reference: string;
}

interface EditEntryDialogProps {
  model: Model | null;
  onOpenChange: (open: boolean) => void;
  onUpdated: (model: Model) => void;
}

export default function EditEntryDialog({
  model,
  onOpenChange,
  onUpdated,
}: EditEntryDialogProps) {
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [license, setLicense] = useState("");
  const [contextLength, setContextLength] = useState("");
  const [capabilities, setCapabilities] = useState("");
  const [servingOptions, setServingOptions] = useState<ServingOptionRow[]>([]);
  const [saving, setSaving] = useState(false);

  // Reset the editable fields from the model prop whenever the dialog opens
  // for a (new) model. Adjusted during render, per
  // https://react.dev/learn/you-might-not-need-an-effect, rather than in an
  // effect, since the fields must stay editable afterwards.
  const [prefilledFor, setPrefilledFor] = useState<Model | null>(null);
  if (model && model !== prefilledFor) {
    setPrefilledFor(model);
    setName(model.name ?? "");
    setDescription(model.description ?? "");
    setLicense(model.license ?? "");
    setContextLength(
      model.context_length != null ? String(model.context_length) : ""
    );
    setCapabilities((model.capabilities ?? []).join(", "));
  }

  useEffect(() => {
    if (!model) return;
    (async () => {
      try {
        const options = await modelService.getModelServingOptions(model.id);
        setServingOptions(
          options.map((o) => ({ engine: o.engine, reference: o.reference }))
        );
      } catch (error) {
        toast(parseApiError(error));
      }
    })();
  }, [model, toast]);

  const updateOption = (
    index: number,
    field: keyof ServingOptionRow,
    value: string
  ) => {
    setServingOptions((prev) =>
      prev.map((option, i) =>
        i === index ? { ...option, [field]: value } : option
      )
    );
  };

  const addOption = () => {
    setServingOptions((prev) => [...prev, { engine: "", reference: "" }]);
  };

  const removeOption = (index: number) => {
    setServingOptions((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!model) return;
    setSaving(true);
    try {
      const updated = await registryService.update(model.id, {
        name,
        description,
        license: license || undefined,
        context_length: contextLength ? parseInt(contextLength, 10) : undefined,
        capabilities: capabilities
          .split(",")
          .map((c) => c.trim())
          .filter(Boolean),
        serving_options: servingOptions.filter(
          (o) => o.engine.trim() && o.reference.trim()
        ),
      });
      toast({
        title: "Success",
        description: "Entry updated",
        variant: "success",
      });
      onUpdated(updated);
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={!!model} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit entry</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="edit-entry-name">Name</Label>
              <Input
                id="edit-entry-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-entry-description">Description</Label>
              <Textarea
                id="edit-entry-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-entry-license">License</Label>
              <Input
                id="edit-entry-license"
                value={license}
                onChange={(e) => setLicense(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-entry-context">Context length</Label>
              <Input
                id="edit-entry-context"
                type="number"
                value={contextLength}
                onChange={(e) => setContextLength(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-entry-capabilities">
                Capabilities (comma separated)
              </Label>
              <Input
                id="edit-entry-capabilities"
                value={capabilities}
                onChange={(e) => setCapabilities(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label>Serving options</Label>
              {servingOptions.map((option, index) => (
                <div
                  key={index}
                  data-testid="serving-option-row"
                  className="flex gap-2"
                >
                  <Input
                    placeholder="Engine"
                    value={option.engine}
                    onChange={(e) =>
                      updateOption(index, "engine", e.target.value)
                    }
                  />
                  <Input
                    placeholder="Reference"
                    value={option.reference}
                    onChange={(e) =>
                      updateOption(index, "reference", e.target.value)
                    }
                  />
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    aria-label={`Remove serving option ${index + 1}`}
                    onClick={() => removeOption(index)}
                  >
                    <TrashIcon className="h-4 w-4" />
                  </Button>
                </div>
              ))}
              <Button type="button" variant="outline" onClick={addOption}>
                Add serving option
              </Button>
            </div>
          </div>
          <DialogFooter className="mt-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={saving} loading={saving}>
              Save
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
