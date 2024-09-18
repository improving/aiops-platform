"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { VectorDBSchema } from "@/types/vectordb";

interface CreateVectorDBInstanceDialogProps {
  vectorDB: VectorDBSchema;
  isOpen: boolean;
  onClose: () => void;
}

export default function CreateVectorDBInstanceDialog({
  vectorDB,
  isOpen,
  onClose,
}: CreateVectorDBInstanceDialogProps) {
  const router = useRouter();
  const [isCreating, setIsCreating] = useState(false);

  const handleCreate = async () => {
    setIsCreating(true);
    try {
      const response = await fetch("/api/v1alpha1/vectordb_instances", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          vectorDB: { id: vectorDB.id },
          configParams: {},
        }),
      });

      if (!response.ok)
        throw new Error("Failed to create vector database instance");

      router.push("/vector-databases/endpoints");
    } catch (error) {
      console.error("Error creating vector database instance:", error);
    } finally {
      setIsCreating(false);
      onClose();
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create Vector Database Instance</DialogTitle>
        </DialogHeader>
        <p>Are you sure you want to create an instance of {vectorDB.name}?</p>
        <div className="flex justify-end space-x-2 mt-4">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleCreate} disabled={isCreating}>
            {isCreating ? "Creating..." : "Create"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
