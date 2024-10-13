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
import { vectorDBService } from "@/services/vectorDBService";
import { useToast } from "@/components/hooks/use-toast";
import { AxiosError } from "axios";

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
  const { toast } = useToast();

  const handleCreate = async () => {
    setIsCreating(true);
    try {
      await vectorDBService.createVectorDBInstance({
        vectorDB: { id: vectorDB.id },
        configParams: {},
      });
      toast({
        title: "Success",
        description: "Vector database instance created successfully",
        variant: "success",
      });
      router.push("/vector-databases/endpoints");
    } catch (error) {
      console.error("Error creating vector database instance:", error);
      if (error instanceof AxiosError) {
        toast({
          title: "Error",
          description: `Failed to create instance: ${error.response?.data?.message || error.message}`,
          variant: "destructive",
        });
      } else {
        toast({
          title: "Error",
          description:
            "An unexpected error occurred while creating the instance",
          variant: "destructive",
        });
      }
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
