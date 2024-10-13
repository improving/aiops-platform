"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Notebook } from "@/types/notebook";
import { OpenInNewWindowIcon } from "@radix-ui/react-icons";
import { Label } from "@/components/ui/label";
import { notebookService } from "@/services/notebookService";
import { useToast } from "@/components/hooks/use-toast";
import { DeleteButton } from "@/components/DeleteButton";
import { parseApiError } from "@/lib/utils";

interface NotebookDetailsProps {
  notebookId: string;
}

export default function NotebookDetails({ notebookId }: NotebookDetailsProps) {
  const [notebook, setNotebook] = useState<Notebook | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();
  const { toast } = useToast();

  useEffect(() => {
    const fetchNotebookDetails = async () => {
      try {
        const data = await notebookService.getNotebookById(notebookId);
        setNotebook(data);
      } catch (error) {
        toast(parseApiError(error));
      } finally {
        setIsLoading(false);
      }
    };
    fetchNotebookDetails();
  }, [notebookId, toast]);

  const handleDelete = async () => {
    await notebookService.deleteNotebook(notebookId);
  };

  if (isLoading) {
    return <div>Loading...</div>;
  }

  if (!notebook) {
    return <div>Notebook not found</div>;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{notebook.name}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4">
          <div className="grid grid-cols-2 items-center gap-4">
            <Label>Type:</Label>
            <span>{notebook.type || "N/A"}</span>
          </div>
          {notebook.type === "jupyter" && (
            <div className="grid grid-cols-2 items-center gap-4">
              <Label>Framework:</Label>
              <span>{notebook.framework || "N/A"}</span>
            </div>
          )}
          <div className="grid grid-cols-2 items-center gap-4">
            <Label>Nvidia GPU:</Label>
            <span>{notebook.nvidia_gpu ? "Yes" : "No"}</span>
          </div>
          <div className="grid grid-cols-2 items-center gap-4">
            <Label>Image:</Label>
            <span>{notebook.image || "N/A"}</span>
          </div>
          <div className="grid grid-cols-2 items-center gap-4">
            <Label>Resources CPU:</Label>
            <span>{notebook.resources_cpu || "N/A"}</span>
          </div>
          <div className="grid grid-cols-2 items-center gap-4">
            <Label>Resources Memory:</Label>
            <span>{notebook.resources_memory || "N/A"}</span>
          </div>
          {notebook.nvidia_gpu && (
            <div className="grid grid-cols-2 items-center gap-4">
              <Label>Resources GPU:</Label>
              <span>{notebook.resources_gpu || "N/A"}</span>
            </div>
          )}
          <div className="grid grid-cols-2 items-center gap-4">
            <Label>Storage Size:</Label>
            <span>{notebook.storage_size || "N/A"}</span>
          </div>
          <div className="grid grid-cols-2 items-center gap-4">
            <Label>Status:</Label>
            <span>{notebook.status || "N/A"}</span>
          </div>
          <div className="grid grid-cols-2 items-center gap-4">
            <Label>Created At:</Label>
            <span>{notebook.created_at || "N/A"}</span>
          </div>
        </div>
      </CardContent>
      <CardFooter>
        <div className="mt-6 flex space-x-4">
          <Button
            onClick={() => window.open(notebook.endpoint, "_blank")}
            disabled={!notebook.ready}
          >
            <OpenInNewWindowIcon className="mr-2 w-4 h-4" />
            Connect
          </Button>
          <DeleteButton
            onDelete={handleDelete}
            onSuccess={() => router.push("/notebooks")}
          />
        </div>
      </CardFooter>
    </Card>
  );
}
