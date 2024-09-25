"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Notebook } from "@/types/notebook";
import { OpenInNewWindowIcon, TrashIcon } from "@radix-ui/react-icons";
import { Label } from "@/components/ui/label";

interface NotebookDetailsProps {
  notebookId: string;
}

export default function NotebookDetails({ notebookId }: NotebookDetailsProps) {
  const [notebook, setNotebook] = useState<Notebook | null>(null);
  const router = useRouter();

  useEffect(() => {
    const fetchNotebookDetails = async () => {
      try {
        const response = await fetch(`/api/v1alpha1/notebooks/${notebookId}`);
        if (!response.ok) {
          throw new Error("Failed to fetch notebook details");
        }
        const data = await response.json();
        setNotebook(data);
      } catch (error) {
        console.error("Error fetching notebook details:", error);
      }
    };
    fetchNotebookDetails();
  }, [notebookId]);

  const handleDelete = async () => {
    try {
      const response = await fetch(`/api/v1alpha1/notebooks/${notebookId}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error("Failed to delete notebook");
      }
      router.push("/notebooks");
    } catch (error) {
      console.error("Error deleting notebook:", error);
    }
  };

  if (!notebook) {
    return <div>Loading...</div>;
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
          <div className="grid grid-cols-2 items-center gap-4">
            <Label>Framework:</Label>
            <span>{notebook.framework || "N/A"}</span>
          </div>
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
        </div>
        <div className="mt-6 flex space-x-4">
          <Button
            onClick={() => window.open(notebook.endpoint, "_blank")}
            disabled={!notebook.ready}
          >
            <OpenInNewWindowIcon className="mr-2 w-4 h-4" />
            Connect to Notebook
          </Button>
          <Button variant="destructive" onClick={handleDelete}>
            <TrashIcon className="mr-2 w-4 h-4" />
            Delete Notebook
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
