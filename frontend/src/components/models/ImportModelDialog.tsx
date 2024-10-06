"use client";

import { useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/hooks/use-toast";

interface ImportModelDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export default function ImportModelDialog({ isOpen, onClose, onSuccess }: ImportModelDialogProps) {
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [subcategory, setSubcategory] = useState("");
  const [size, setSize] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const { toast } = useToast();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      const response = await fetch("/api/v1alpha1/models", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name,
          modelId,
          description,
          category,
          subcategory,
          size: parseInt(size, 10),
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to import model");
      }

      onSuccess();
    } catch (error) {
      console.error("Error importing model:", error);
      toast({
        title: "Error",
        description: "Failed to import model. Please try again.",
        variant: "destructive",
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Import Model</DialogTitle>
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
              required
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
              required
            />
            <Input
              type="number"
              placeholder="Size (in bytes)"
              value={size}
              onChange={(e) => setSize(e.target.value)}
              required
            />
          </div>
          <DialogFooter className="mt-4">
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={isLoading}>
              {isLoading ? "Importing..." : "Import"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}