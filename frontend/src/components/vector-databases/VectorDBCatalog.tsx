"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { VectorDBSchema } from "@/types/vectordb";
import CreateVectorDBInstanceDialog from "./CreateVectorDBInstanceDialog";
import { RocketIcon } from "@radix-ui/react-icons";
import { vectorDBService } from "@/services/vectorDBService";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";

export default function VectorDBCatalog() {
  const [vectorDBs, setVectorDBs] = useState<VectorDBSchema[]>([]);
  const [selectedVectorDB, setSelectedVectorDB] =
    useState<VectorDBSchema | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const { toast } = useToast();

  useEffect(() => {
    const fetchVectorDBs = async () => {
      try {
        setIsLoading(true);
        const data = await vectorDBService.getVectorDBs();
        setVectorDBs(data);
      } catch (error) {
        toast(parseApiError(error));
      } finally {
        setIsLoading(false);
      }
    };
    fetchVectorDBs();
  }, [toast]);

  const handleLaunch = (vectorDB: VectorDBSchema) => {
    setSelectedVectorDB(vectorDB);
    setIsDialogOpen(true);
  };

  if (isLoading) {
    return <div>Loading...</div>;
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      {vectorDBs.map((vectorDB) => (
        <Card key={vectorDB.id}>
          <CardHeader>
            <CardTitle>{vectorDB.name}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-4">{vectorDB.description}</p>
            <Button onClick={() => handleLaunch(vectorDB)}>
              <RocketIcon className="mr-2 w-4 h-4" />
              Launch
            </Button>
          </CardContent>
        </Card>
      ))}
      {selectedVectorDB && (
        <CreateVectorDBInstanceDialog
          vectorDB={selectedVectorDB}
          isOpen={isDialogOpen}
          onClose={() => setIsDialogOpen(false)}
        />
      )}
    </div>
  );
}
