"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { VectorDBSchema } from "@/types/vectordb";
import CreateVectorDBInstanceDialog from "./CreateVectorDBInstanceDialog";
import { RocketIcon } from "@radix-ui/react-icons";
import { vectorDBService } from "@/services/vectorDBService";
import { useToast } from "@/components/hooks/use-toast";
import { GetVectorDBIcon, parseApiError } from "@/lib/utils";
import { DisplayCard } from "@/components/ui/DisplayCard";
import { CardGridSkeleton } from "@/components/LoadingState";

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
    return <CardGridSkeleton />;
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      {vectorDBs.map((vectorDB) => (
        <DisplayCard
          key={vectorDB.id}
          icon={GetVectorDBIcon(vectorDB.chart_name)}
          title={vectorDB.name}
          content={<p>{vectorDB.description}</p>}
          footer={
            <Button onClick={() => handleLaunch(vectorDB)}>
              <RocketIcon className="mr-2 w-4 h-4" />
              Launch
            </Button>
          }
        />
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
