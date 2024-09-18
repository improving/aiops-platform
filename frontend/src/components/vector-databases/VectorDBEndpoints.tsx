"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { VectorDBInstanceSchema } from "@/types/vectordb";
import { RocketIcon, TrashIcon } from "@radix-ui/react-icons";
import Link from "next/link";

export default function VectorDBEndpoints() {
  const [instances, setInstances] = useState<VectorDBInstanceSchema[]>([]);

  useEffect(() => {
    fetchInstances();
  }, []);

  const fetchInstances = async () => {
    try {
      const response = await fetch("/api/v1alpha1/vectordb_instances");
      if (!response.ok)
        throw new Error("Failed to fetch vector database instances");
      const data = await response.json();
      setInstances(data);
    } catch (error) {
      console.error("Error fetching vector database instances:", error);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      const response = await fetch(`/api/v1alpha1/vectordb_instances/${id}`, {
        method: "DELETE",
      });
      if (!response.ok)
        throw new Error("Failed to delete vector database instance");
      fetchInstances();
    } catch (error) {
      console.error("Error deleting vector database instance:", error);
    }
  };

  return (
    <>
      {instances.length === 0 ? (
        <div className="text-center">
          <p className="mb-4">No vector databases available.</p>
          <Link href="/vector-databases/catalog">
            <Button>
              <RocketIcon className="mr-2 h-4 w-4" />
              Launch
            </Button>
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {instances.map((instance) => (
            <Card key={instance.id}>
              <CardHeader>
                <CardTitle>{instance.vectorDB.name}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="mb-2">Endpoint: {instance.endpoint}</p>
                <Button
                  variant="destructive"
                  onClick={() => handleDelete(instance.id)}
                >
                  <TrashIcon className="mr-2 w-4 h-4" />
                  Delete
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
