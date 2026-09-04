"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { VectorDBInstanceSchema } from "@/types/vectordb";
import {
  ClipboardCopyIcon,
  OpenInNewWindowIcon,
  RocketIcon,
} from "@radix-ui/react-icons";
import Link from "next/link";
import { vectorDBService } from "@/services/vectorDBService";
import { useToast } from "@/components/hooks/use-toast";
import { DeleteButton } from "@/components/DeleteButton";
import { GetVectorDBIcon, parseApiError } from "@/lib/utils";
import { DisplayCard } from "@/components/ui/DisplayCard";
import { RefreshButton } from "@/components/RefreshButton";
import { isNonTerminal, usePolling } from "@/hooks/usePolling";

export default function VectorDBEndpoints() {
  const [instances, setInstances] = useState<VectorDBInstanceSchema[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const { toast } = useToast();

  const fetchInstances = useCallback(
    async (options?: { silent?: boolean }) => {
      try {
        const data = await vectorDBService.getVectorDBInstances();
        setInstances(data);
      } catch (error) {
        if (!options?.silent) toast(parseApiError(error));
      } finally {
        setIsLoading(false);
      }
    },
    [toast]
  );

  useEffect(() => {
    fetchInstances();
  }, [fetchInstances]);

  const pollInstances = useCallback(
    () => fetchInstances({ silent: true }),
    [fetchInstances]
  );
  usePolling(pollInstances, instances.some(isNonTerminal));

  const filteredInstances = instances.filter((instance) =>
    instance.vectorDB.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleDelete = async (id: string) => {
    await vectorDBService.deleteVectorDBInstance(id);
  };

  if (isLoading) {
    return <div>Loading...</div>;
  }

  return (
    <>
      <div className="flex justify-between items-center mb-4">
        <Input
          type="text"
          placeholder="Search by name..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="max-w-xs"
        />
        <RefreshButton onRefresh={fetchInstances} />
      </div>

      {filteredInstances.length === 0 ? (
        <div className="text-center">
          <p className="mb-4">No vector databases available.</p>
          <Link href="/vector-databases/catalog">
            <Button icon={<RocketIcon className="mr-2 h-4 w-4" />}>
              Launch
            </Button>
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredInstances.map((instance) => (
            <DisplayCard
              key={instance.id}
              icon={GetVectorDBIcon(instance.vectorDB.chart_name)}
              title={instance.vectorDB.name}
              description={`ID: ${instance.id}`}
              content={
                <>
                  <div className="flex flex-wrap gap-2 mb-3">
                    <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-sm">
                      {instance.vectorDB.chart_name}
                    </span>
                    {instance.ready ? (
                      <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                        Ready
                      </span>
                    ) : (
                      <span className="px-2 py-1 bg-red-100 text-red-800 rounded-full text-sm">
                        {instance.status || "In Progress"}
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-gray-600 mb-2">
                    <strong>Endpoint: </strong>
                    <span
                      className={
                        instance.ready ? "text-green-500" : "text-red-500"
                      }
                    >
                      <OpenInNewWindowIcon className="w-4 h-4 inline-block" />
                      <a href={`${instance.endpoint}/docs`} target="_blank">
                        {instance.endpoint || "N/A"}
                      </a>
                      <Button
                        variant="outline"
                        onClick={() =>
                          navigator.clipboard.writeText(instance.endpoint || "")
                        }
                        className="ml-2"
                        icon={<ClipboardCopyIcon className="w-4 h-4" />}
                      ></Button>
                    </span>
                  </p>
                </>
              }
              footer={
                <DeleteButton
                  onDelete={() => handleDelete(instance.id)}
                  onSuccess={() => fetchInstances()}
                />
              }
            />
          ))}
        </div>
      )}
    </>
  );
}
