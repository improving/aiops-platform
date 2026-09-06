"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { VectorDBInstanceSchema } from "@/types/vectordb";
import { OpenInNewWindowIcon, RocketIcon } from "@radix-ui/react-icons";
import { CopyButton } from "@/components/CopyButton";
import Link from "next/link";
import { vectorDBService } from "@/services/vectorDBService";
import { useToast } from "@/components/hooks/use-toast";
import { DeleteButton } from "@/components/DeleteButton";
import { GetVectorDBIcon, parseApiError } from "@/lib/utils";
import { DisplayCard } from "@/components/ui/DisplayCard";
import { RefreshButton } from "@/components/RefreshButton";
import { isNonTerminal, usePolling } from "@/hooks/usePolling";
import { ShowCredentialButton } from "@/components/vector-databases/ShowCredentialButton";
import { CardGridSkeleton } from "@/components/LoadingState";
import {
  ListControls,
  ShowMore,
  applyListControls,
  useListState,
} from "@/components/ListControls";

export default function VectorDBEndpoints() {
  const [instances, setInstances] = useState<VectorDBInstanceSchema[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [listState, updateList, nextPage] = useListState();
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
    (async () => {
      await fetchInstances();
    })();
  }, [fetchInstances]);

  const pollInstances = useCallback(
    () => fetchInstances({ silent: true }),
    [fetchInstances]
  );
  usePolling(pollInstances, instances.some(isNonTerminal));

  const filteredInstances = instances.filter((instance) =>
    instance.vectorDB.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const { visible, total, hasMore } = applyListControls(
    filteredInstances,
    listState,
    { name: (i) => i.vectorDB.name, ready: (i) => i.ready }
  );

  const handleDelete = async (id: string) => {
    await vectorDBService.deleteVectorDBInstance(id);
  };

  if (isLoading) {
    return <CardGridSkeleton />;
  }

  return (
    <>
      <div className="flex flex-wrap justify-between items-center gap-2 mb-4">
        <div className="flex flex-wrap gap-2">
          <Input
            type="text"
            placeholder="Search by name..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="max-w-xs"
          />
          <ListControls state={listState} onChange={updateList} />
        </div>
        <RefreshButton onRefresh={fetchInstances} />
      </div>

      {instances.length === 0 ? (
        <div className="text-center">
          <p className="mb-4">No vector database instances yet.</p>
          <Link href="/vector-databases/catalog">
            <Button icon={<RocketIcon className="mr-2 h-4 w-4" />}>
              Launch
            </Button>
          </Link>
        </div>
      ) : total === 0 ? (
        <p className="text-muted-foreground">No instances match.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {visible.map((instance) => (
            <DisplayCard
              key={instance.id}
              icon={GetVectorDBIcon(instance.vectorDB.chart_name)}
              title={
                <Link
                  href={`/vector-databases/endpoints/${instance.id}`}
                  className="hover:text-blue-500 underline"
                >
                  {instance.vectorDB.name}
                </Link>
              }
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
                      {instance.endpoint && (
                        <span className="ml-2">
                          <CopyButton
                            label={`${instance.vectorDB.name} endpoint`}
                            text={instance.endpoint}
                          />
                        </span>
                      )}
                    </span>
                  </p>
                  <p className="text-sm text-gray-600 mb-2">
                    <strong>API endpoint: </strong>
                    <span className="break-all">
                      {instance.api_endpoint || "N/A"}
                    </span>
                    {instance.api_endpoint && (
                      <span className="ml-2">
                        <CopyButton
                          label={`${instance.vectorDB.name} API endpoint`}
                          text={instance.api_endpoint}
                        />
                      </span>
                    )}
                  </p>
                </>
              }
              footer={
                <div className="flex flex-wrap gap-2">
                  <ShowCredentialButton instance={instance} />
                  <DeleteButton
                    onDelete={() => handleDelete(instance.id)}
                    onSuccess={() => fetchInstances()}
                  />
                </div>
              }
            />
          ))}
        </div>
      )}
      <ShowMore
        hasMore={hasMore}
        onClick={nextPage}
        shown={visible.length}
        total={total}
      />
    </>
  );
}
