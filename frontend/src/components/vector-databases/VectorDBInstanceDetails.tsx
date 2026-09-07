"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Label } from "@/components/ui/label";
import { DetailRow } from "@/components/DetailRow";
import { VectorDBInstanceSchema } from "@/types/vectordb";
import { vectorDBService } from "@/services/vectorDBService";
import { useToast } from "@/components/hooks/use-toast";
import { DeleteButton } from "@/components/DeleteButton";
import { CopyButton } from "@/components/CopyButton";
import { CodeSnippet } from "@/components/CodeSnippet";
import { DetailSkeleton } from "@/components/LoadingState";
import { DisplayCard } from "@/components/ui/DisplayCard";
import { GetVectorDBIcon, parseApiError } from "@/lib/utils";
import { isNonTerminal, usePolling } from "@/hooks/usePolling";
import { ShowCredentialButton } from "@/components/vector-databases/ShowCredentialButton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LogsQuery } from "@/types/models";
import { StatusBadge } from "@/components/instances/StatusBadge";
import { ErrorBanner } from "@/components/instances/ErrorBanner";
import { InstanceActions } from "@/components/instances/InstanceActions";
import { InspectionTabs } from "@/components/instances/InspectionTabs";
import { NotFoundOrError } from "@/components/instances/NotFoundOrError";

// This page's rows always wrapped the value in this class (unlike the
// inference and notebook pages' mostly-bare rows), so DetailRow is told to
// reproduce it explicitly rather than by default.
const ROW_VALUE_CLASS = "flex items-center gap-2 break-all";

export default function VectorDBInstanceDetails({ id }: { id: string }) {
  const [instance, setInstance] = useState<VectorDBInstanceSchema | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const router = useRouter();
  const { toast } = useToast();

  const fetchInstance = useCallback(
    async (options?: { silent?: boolean }) => {
      try {
        setInstance(await vectorDBService.getVectorDBInstance(id));
      } catch (error) {
        if (!options?.silent) {
          toast(parseApiError(error));
          setLoadError(error);
        }
      } finally {
        setLoading(false);
      }
    },
    [id, toast]
  );

  useEffect(() => {
    (async () => {
      await fetchInstance();
    })();
  }, [fetchInstance]);

  const poll = useCallback(
    () => fetchInstance({ silent: true }),
    [fetchInstance]
  );
  usePolling(poll, instance ? isNonTerminal(instance) : false);

  const fetchLogs = useCallback(
    (query: LogsQuery) => vectorDBService.getVectorDBInstanceLogs(id, query),
    [id]
  );
  const fetchEvents = useCallback(
    () => vectorDBService.getVectorDBInstanceEvents(id),
    [id]
  );

  if (loading) return <DetailSkeleton />;
  if (!instance) {
    return (
      <NotFoundOrError error={loadError} noun="vector database instance" />
    );
  }

  const apiBase = instance.api_endpoint?.replace(/\/$/, "") ?? "<api endpoint>";
  const configEntries = Object.entries(instance.configParams ?? {});

  return (
    <Tabs defaultValue="details" className="w-full">
      <TabsList className="grid w-full grid-cols-3">
        <TabsTrigger value="details">Details</TabsTrigger>
        <TabsTrigger value="logs">Logs</TabsTrigger>
        <TabsTrigger value="events">Events</TabsTrigger>
      </TabsList>
      <TabsContent value="details">
        <DisplayCard
          icon={GetVectorDBIcon(instance.vectorDB.chart_name)}
          title={instance.vectorDB.name}
          description={`ID: ${instance.id}`}
          onRefresh={() => fetchInstance()}
          content={
            <div className="grid gap-4">
              <ErrorBanner
                error={instance.last_error}
                at={instance.last_error_at}
              />
              <DetailRow label="Chart" valueClassName={ROW_VALUE_CLASS}>
                {instance.vectorDB.chart_name}
              </DetailRow>
              <DetailRow label="Status" valueClassName={ROW_VALUE_CLASS}>
                <StatusBadge ready={instance.ready} status={instance.status} />
              </DetailRow>
              <DetailRow label="Endpoint" valueClassName={ROW_VALUE_CLASS}>
                <span
                  className={instance.ready ? "text-green-500" : "text-red-500"}
                >
                  {instance.endpoint || "N/A"}
                </span>
                {instance.endpoint && (
                  <CopyButton label="endpoint" text={instance.endpoint} />
                )}
              </DetailRow>
              <DetailRow label="API endpoint" valueClassName={ROW_VALUE_CLASS}>
                {instance.api_endpoint || "N/A"}
                {instance.api_endpoint && (
                  <CopyButton
                    label="API endpoint"
                    text={instance.api_endpoint}
                  />
                )}
              </DetailRow>
              {configEntries.length > 0 && (
                <DetailRow label="Configuration" valueClassName={ROW_VALUE_CLASS}>
                  <span className="text-sm text-muted-foreground">
                    {configEntries
                      .map(([k, v]) => `${k}=${String(v)}`)
                      .join(", ")}
                  </span>
                </DetailRow>
              )}
              <div className="grid grid-cols-2 items-start gap-4">
                <Label>Access</Label>
                <div className="space-y-2 text-sm text-muted-foreground">
                  <p>
                    The API endpoint is protected at the gateway; send the
                    instance API key in the header shown by &quot;Show
                    credential&quot;.
                  </p>
                  <CodeSnippet
                    label="curl example"
                    code={`curl -H "api-key: <api key>" ${apiBase}/collections`}
                  />
                </div>
              </div>
            </div>
          }
          footer={
            <div className="flex flex-wrap gap-2">
              <InstanceActions
                status={instance.status}
                onRestart={() =>
                  vectorDBService.restartVectorDBInstance(instance.id)
                }
                onDone={() => fetchInstance()}
              />
              <ShowCredentialButton instance={instance} />
              <DeleteButton
                onDelete={() =>
                  vectorDBService.deleteVectorDBInstance(instance.id)
                }
                onSuccess={() => router.push("/vector-databases/endpoints")}
              />
            </div>
          }
        />
      </TabsContent>
      <InspectionTabs fetchLogs={fetchLogs} fetchEvents={fetchEvents} />
    </Tabs>
  );
}
