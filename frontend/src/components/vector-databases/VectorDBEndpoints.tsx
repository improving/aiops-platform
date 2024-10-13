"use client";

import { useEffect, useState } from "react";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { VectorDBInstanceSchema } from "@/types/vectordb";
import { RocketIcon, TrashIcon } from "@radix-ui/react-icons";
import Link from "next/link";
import { vectorDBService } from "@/services/vectorDBService";
import { useToast } from "@/components/hooks/use-toast";
import { AxiosError } from "axios";
import { DeleteButton } from "@/components/DeleteButton";

export default function VectorDBEndpoints() {
  const [instances, setInstances] = useState<VectorDBInstanceSchema[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const { toast } = useToast();

  const fetchInstances = async () => {
    try {
      setIsLoading(true);
      const data = await vectorDBService.getVectorDBInstances();
      setInstances(data);
    } catch (error) {
      console.error("Error fetching vector database instances:", error);
      toast({
        title: "Error",
        description: "Failed to fetch vector database instances",
        variant: "destructive",
      });
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchInstances();
  }, [fetchInstances, toast]);

  const handleDelete = async (id: string) => {
    await vectorDBService.deleteVectorDBInstance(id);
  };

  if (isLoading) {
    return <div>Loading...</div>;
  }

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
              </CardContent>
              <CardFooter>
                <DeleteButton
                  onDelete={() => handleDelete(instance.id)}
                  onSuccess={() => fetchInstances()}
                />
              </CardFooter>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
