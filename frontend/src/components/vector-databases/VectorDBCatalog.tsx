"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { VectorDBSchema } from "@/types/vectordb";
import CreateVectorDBInstanceDialog from "./CreateVectorDBInstanceDialog";
import { RocketIcon } from "@radix-ui/react-icons";

export default function VectorDBCatalog() {
  const [vectorDBs, setVectorDBs] = useState<VectorDBSchema[]>([]);
  const [selectedVectorDB, setSelectedVectorDB] =
    useState<VectorDBSchema | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);

  useEffect(() => {
    fetchVectorDBs();
  }, []);

  const fetchVectorDBs = async () => {
    try {
      const response = await fetch("/api/v1alpha1/vectordb");
      if (!response.ok) throw new Error("Failed to fetch vector databases");
      const data = await response.json();
      setVectorDBs(data);
    } catch (error) {
      console.error("Error fetching vector databases:", error);
    }
  };

  const handleLaunch = (vectorDB: VectorDBSchema) => {
    setSelectedVectorDB(vectorDB);
    setIsDialogOpen(true);
  };

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
