"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Notebook } from "@/types/notebook";

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
        <div className="grid grid-cols-2 gap-4">
          <div>
            <strong>Type:</strong> {notebook.type || "N/A"}
          </div>
          {notebook.type == "jupyter" && (
            <div>
              <strong>Framework:</strong> {notebook.framework || "N/A"}
            </div>
          )}
          <div>
            <strong>Nvidia GPU:</strong> {notebook.nvidia_gpu ? "Yes" : "No"}
          </div>
          <div>
            <strong>Resources CPU:</strong> {notebook.resources_cpu || "N/A"}
          </div>
          <div>
            <strong>Resources Memory:</strong> {notebook.resources_memory || "N/A"}
          </div>
          {notebook.nvidia_gpu && (
            <div>
              <strong>Resources GPU:</strong> {notebook.resources_gpu || "N/A"}
            </div>
          )}
          <div>
            <strong>Storage Size:</strong> {notebook.storage_size || "N/A"}
          </div>
          <div>
            <strong>Status:</strong> {notebook.status || "N/A"}
          </div>
          <div>
            <strong>Endpoint:</strong> {notebook.endpoint || "N/A"}
          </div>
        </div>
        <div className="mt-6 flex space-x-4">
          <Button
            onClick={() => window.open(notebook.endpoint, "_blank")}
            disabled={!notebook.ready}
          >
            Connect to Notebook
          </Button>
          <Button variant="destructive" onClick={handleDelete}>
            Delete Notebook
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
