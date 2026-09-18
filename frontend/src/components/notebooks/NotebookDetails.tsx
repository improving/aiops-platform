"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Notebook } from "@/types/notebook";
import { OpenInNewWindowIcon } from "@radix-ui/react-icons";
import { notebookService } from "@/services/notebookService";
import { useToast } from "@/components/hooks/use-toast";
import { DeleteButton } from "@/components/DeleteButton";
import { DetailRow } from "@/components/DetailRow";
import { parseApiError } from "@/lib/utils";
import { DisplayCard } from "@/components/ui/DisplayCard";
import { isNonTerminal, usePolling } from "@/hooks/usePolling";
import { DetailSkeleton } from "@/components/LoadingState";
import { CopyButton } from "@/components/CopyButton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LogsQuery } from "@/types/models";
import { StatusBadge } from "@/components/instances/StatusBadge";
import { ErrorBanner } from "@/components/instances/ErrorBanner";
import { LaunchProgress } from "@/components/instances/LaunchProgress";
import { InspectionTabs } from "@/components/instances/InspectionTabs";
import { NotFoundOrError } from "@/components/instances/NotFoundOrError";

interface NotebookDetailsProps {
  notebookId: string;
}

export default function NotebookDetails({ notebookId }: NotebookDetailsProps) {
  const [notebook, setNotebook] = useState<Notebook | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const router = useRouter();
  const { toast } = useToast();

  const fetchNotebookDetails = useCallback(
    async (options?: { silent?: boolean }) => {
      try {
        const data = await notebookService.getNotebookById(notebookId);
        setNotebook(data);
      } catch (error) {
        if (!options?.silent) {
          toast(parseApiError(error));
          setLoadError(error);
        }
      } finally {
        setIsLoading(false);
      }
    },
    [notebookId, toast]
  );

  useEffect(() => {
    (async () => {
      await fetchNotebookDetails();
    })();
  }, [fetchNotebookDetails]);

  const pollNotebookDetails = useCallback(
    () => fetchNotebookDetails({ silent: true }),
    [fetchNotebookDetails]
  );
  usePolling(pollNotebookDetails, notebook ? isNonTerminal(notebook) : false);

  const fetchLogs = useCallback(
    (query: LogsQuery) => notebookService.getNotebookLogs(notebookId, query),
    [notebookId]
  );
  const fetchEvents = useCallback(
    () => notebookService.getNotebookEvents(notebookId),
    [notebookId]
  );

  const handleDelete = async () => {
    await notebookService.deleteNotebook(notebookId);
  };

  if (isLoading) {
    return <DetailSkeleton />;
  }

  if (!notebook) {
    return <NotFoundOrError error={loadError} noun="notebook" />;
  }

  return (
    <Tabs defaultValue="details" className="w-full">
      <TabsList className="grid w-full grid-cols-3">
        <TabsTrigger value="details">Details</TabsTrigger>
        <TabsTrigger value="logs">Logs</TabsTrigger>
        <TabsTrigger value="events">Events</TabsTrigger>
      </TabsList>
      <TabsContent value="details">
        <DisplayCard
          icon={`/notebooks/${notebook.type}.png`}
          title={notebook.name}
          description={`ID: ${notebook.id}`}
          onRefresh={fetchNotebookDetails}
          content={
            <div className="grid gap-4">
              <ErrorBanner
                error={notebook.last_error}
                at={notebook.last_error_at}
              />
              <DetailRow label="Type:">{notebook.type || "N/A"}</DetailRow>
              {notebook.endpoint && (
                <DetailRow
                  label="Endpoint:"
                  valueClassName="flex items-center gap-2"
                >
                  <span className="break-all">{notebook.endpoint}</span>
                  <CopyButton label="notebook URL" text={notebook.endpoint} />
                </DetailRow>
              )}
              {notebook.type === "jupyter" && (
                <DetailRow label="Framework:">
                  {notebook.framework || "N/A"}
                </DetailRow>
              )}
              <DetailRow label="Nvidia GPU:">
                {notebook.nvidia_gpu ? "Yes" : "No"}
              </DetailRow>
              <DetailRow label="Image:">{notebook.image || "N/A"}</DetailRow>
              <DetailRow label="Resources CPU:">
                {notebook.resources_cpu || "N/A"}
              </DetailRow>
              <DetailRow label="Resources Memory:">
                {notebook.resources_memory || "N/A"}
              </DetailRow>
              {notebook.nvidia_gpu && (
                <DetailRow label="Resources GPU:">
                  {notebook.resources_gpu || "N/A"}
                </DetailRow>
              )}
              <DetailRow label="Storage Size:">
                {notebook.storage_size || "N/A"}
              </DetailRow>
              <DetailRow label="Status:">
                <StatusBadge
                  ready={notebook.ready}
                  status={notebook.status}
                  label={notebook.status || "Pending"}
                />
              </DetailRow>
              {notebook.launch && !notebook.ready && (
                <DetailRow label="Launch:">
                  <LaunchProgress
                    launch={notebook.launch}
                    ready={notebook.ready}
                  />
                </DetailRow>
              )}
              <DetailRow label="Created At:">
                {notebook.created_at || "N/A"}
              </DetailRow>
            </div>
          }
          footer={
            <div className="mt-6 flex space-x-4">
              <Button
                onClick={() => window.open(notebook.endpoint, "_blank")}
                disabled={!notebook.ready}
                icon={<OpenInNewWindowIcon className="mr-2 w-4 h-4" />}
              >
                Connect
              </Button>
              <DeleteButton
                onDelete={handleDelete}
                onSuccess={() => router.push("/notebooks")}
              />
            </div>
          }
        />
      </TabsContent>
      <InspectionTabs fetchLogs={fetchLogs} fetchEvents={fetchEvents} />
    </Tabs>
  );
}
