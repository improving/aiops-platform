"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/hooks/use-toast";
import { AxiosError } from "axios";
import { TrashIcon } from "@radix-ui/react-icons";

interface DeleteButtonProps {
  onDelete: () => Promise<void>;
  onSuccess?: () => void;
  onError?: (error: AxiosError) => void;
  buttonText?: string;
  modalTitle?: string;
  modalDescription?: string;
  successToastMessage?: string;
  errorToastMessage?: string;
}

export function DeleteButton({
  onDelete,
  onSuccess,
  onError,
  buttonText = "Delete",
  modalTitle = "Confirm Deletion",
  modalDescription = "Are you sure you want to delete this item? This action cannot be undone.",
  successToastMessage = "Item deleted successfully",
  errorToastMessage = "Failed to delete item",
}: DeleteButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const { toast } = useToast();

  const handleDelete = async () => {
    setIsDeleting(true);
    try {
      await onDelete();
      setIsOpen(false);
      toast({
        title: "Success",
        description: successToastMessage,
        variant: "success",
      });
      onSuccess?.();
    } catch (error) {
      toast({
        title: "Error",
        description: errorToastMessage,
        variant: "destructive",
      });
      onError?.(error as AxiosError);
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <>
      <Button
        variant="destructive"
        onClick={() => setIsOpen(true)}
        disabled={isDeleting}
        icon={<TrashIcon className="w-4 h-4" />}
      >
        {buttonText}
      </Button>
      <Dialog open={isOpen} onOpenChange={setIsOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{modalTitle}</DialogTitle>
            <DialogDescription>{modalDescription}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsOpen(false)}
              disabled={isDeleting}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleDelete}
              loading={isDeleting}
            >
              {isDeleting ? "Deleting..." : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
