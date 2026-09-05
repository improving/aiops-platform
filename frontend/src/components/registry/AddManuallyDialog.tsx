"use client";

import { useState } from "react";
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
import { registryService } from "@/services/registryService";
import { parseApiError } from "@/lib/utils";
import type { Model } from "@/types/models";

interface ServingOptionRow {
  engine: string;
  reference: string;
}

interface AddManuallyDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (model: Model) => void;
}

export default function AddManuallyDialog({
  open,
  onOpenChange,
  onCreated,
}: AddManuallyDialogProps) {
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [subcategory, setSubcategory] = useState("");
  const [size, setSize] = useState("");
  const [license, setLicense] = useState("");
  const [servingOptions, setServingOptions] = useState<ServingOptionRow[]>([
    { engine: "", reference: "" },
  ]);
  const [isLoading, setIsLoading] = useState(false);

  const reset = () => {
    setName("");
    setModelId("");
    setDescription("");
    setCategory("");
    setSubcategory("");
    setSize("");
    setLicense("");
    setServingOptions([{ engine: "", reference: "" }]);
  };

  const close = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

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
    setIsLoading(true);
    try {
      const model = await registryService.manualCreate({
        name,
        model_id: modelId,
        category,
        subcategory: subcategory || undefined,
        description: description || undefined,
        size: size ? parseInt(size, 10) : undefined,
        license: license || undefined,
        serving_options: servingOptions.filter(
          (o) => o.engine.trim() && o.reference.trim()
        ),
      });
      toast({
        title: "Success",
        description: "Model added to the registry",
        variant: "success",
      });
      onCreated(model);
      close(false);
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add manually</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <div className="space-y-4">
            <Input
              placeholder="Model Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
            <Input
              placeholder="Model ID"
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
              required
            />
            <Textarea
              placeholder="Description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <Input
              placeholder="Category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              required
            />
            <Input
              placeholder="Subcategory"
              value={subcategory}
              onChange={(e) => setSubcategory(e.target.value)}
            />
            <Input
              type="number"
              placeholder="Size (in bytes)"
              value={size}
              onChange={(e) => setSize(e.target.value)}
            />
            <Input
              placeholder="License"
              value={license}
              onChange={(e) => setLicense(e.target.value)}
            />

            <div className="space-y-2">
              <Label>Serving options</Label>
              {servingOptions.map((option, index) => (
                <div
                  key={index}
                  data-testid="serving-option-row"
                  className="flex gap-2"
                >
                  <Input
                    placeholder="Engine (e.g. HuggingFace)"
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
                  {servingOptions.length > 1 && (
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      aria-label={`Remove serving option ${index + 1}`}
                      onClick={() => removeOption(index)}
                    >
                      <TrashIcon className="h-4 w-4" />
                    </Button>
                  )}
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
              onClick={() => close(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isLoading} loading={isLoading}>
              {isLoading ? "Adding..." : "Add"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
