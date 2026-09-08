"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import GrafanaEmbed from "@/components/GrafanaEmbed";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Adapter,
  Credential,
  InferenceInstance,
  InferenceInstanceDashboard,
  LogsQuery,
} from "@/types/models";
import { DetailRow } from "@/components/DetailRow";
import { StatusBadge } from "@/components/instances/StatusBadge";
import { ErrorBanner } from "@/components/instances/ErrorBanner";
import { InstanceActions } from "@/components/instances/InstanceActions";
import { InspectionTabs } from "@/components/instances/InspectionTabs";
import { NotFoundOrError } from "@/components/instances/NotFoundOrError";
import { isNonTerminal, usePolling } from "@/hooks/usePolling";
import JaegerEmbed from "@/components/JaegerEmbed";
import { Input } from "@/components/ui/input";
import { modelService, upstreamModel } from "@/services/modelService";
import { useToast } from "@/components/hooks/use-toast";
import { DeleteButton } from "@/components/DeleteButton";
import { Combobox } from "@/components/ui/combobox";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { GetModelIcon, parseApiError } from "@/lib/utils";
import { DisplayCard } from "@/components/ui/DisplayCard";
import { DetailSkeleton } from "@/components/LoadingState";
import { CopyButton } from "@/components/CopyButton";
import { InstanceAccess } from "@/components/instances/InstanceAccess";

const timeRangeOptions = [
  { label: "Last 5 minutes", value: 5 * 60 * 1000 },
  { label: "Last 15 minutes", value: 15 * 60 * 1000 },
  { label: "Last 30 minutes", value: 30 * 60 * 1000 },
  { label: "Last 1 hour", value: 60 * 60 * 1000 },
  { label: "Last 3 hours", value: 3 * 60 * 60 * 1000 },
  { label: "Last 6 hours", value: 6 * 60 * 60 * 1000 },
  { label: "Last 12 hours", value: 12 * 60 * 60 * 1000 },
  { label: "Last 24 hours", value: 24 * 60 * 60 * 1000 },
  { label: "Last 2 days", value: 2 * 24 * 60 * 60 * 1000 },
];

export default function InferenceEndpointDetailsPage({
  params,
}: {
  params: { id: string };
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [inferenceInstance, setInferenceInstance] =
    useState<InferenceInstance | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [dashboards, setDashboards] = useState<InferenceInstanceDashboard[]>(
    []
  );
  const [selectedTimeRange, setSelectedTimeRange] = useState(
    timeRangeOptions[0]
  );
  const [activeTab, setActiveTab] = useState(
    searchParams.get("tab") || "details"
  );
  const [selectedAdapter, setSelectedAdapter] = useState<Adapter | null>(null);
  const [jaegerLimit, setJaegerLimit] = useState(20);
  const [now, setNow] = useState(() => Date.now());
  const timeRangeItems = timeRangeOptions.map((option) => ({
    value: option.label,
    onSelect: () => {
      setSelectedTimeRange(option);
      setNow(Date.now());
    },
  }));
  const [credential, setCredential] = useState<Credential | null>(null);
  const [credentialDialogOpen, setCredentialDialogOpen] = useState(false);
  const [credentialLoading, setCredentialLoading] = useState(false);
  const { toast } = useToast();

  const handleShowApiKey = useCallback(
    async (reveal = false) => {
      setCredentialLoading(true);
      try {
        const data = await modelService.getInferenceInstanceCredential(
          params.id,
          reveal
        );
        setCredential(data);
        setCredentialDialogOpen(true);
        // A non-admin's reveal request is a 200 with value: null (the
        // backend does not 403 it), so the UI must call that out itself.
        if (reveal && !data.value) {
          toast({
            title: "Only an admin can reveal this key again",
            variant: "destructive",
          });
        }
      } catch (error) {
        toast(parseApiError(error));
      } finally {
        setCredentialLoading(false);
      }
    },
    [params.id, toast]
  );

  const fetchInferenceInstance = useCallback(async () => {
    try {
      const data = await modelService.getInferenceInstance(params.id);
      setInferenceInstance(data);
      setNow(Date.now());
    } catch (error) {
      toast(parseApiError(error));
      setLoadError(error);
    } finally {
      setLoading(false);
    }
  }, [params.id, toast]);

  const fetchDashboards = useCallback(async () => {
    try {
      const data = await modelService.getInferenceInstanceDashboards(params.id);
      setDashboards(data);
    } catch (error) {
      toast(parseApiError(error));
    }
  }, [params.id, toast]);

  const fetchLogs = useCallback(
    (query: LogsQuery) =>
      modelService.getInferenceInstanceLogs(params.id, query),
    [params.id]
  );
  const fetchEvents = useCallback(
    () => modelService.getInferenceInstanceEvents(params.id),
    [params.id]
  );
  const poll = useCallback(async () => {
    try {
      setInferenceInstance(await modelService.getInferenceInstance(params.id));
    } catch {
      // A silent refresh: the next one may succeed.
    }
  }, [params.id]);
  usePolling(
    poll,
    inferenceInstance ? isNonTerminal(inferenceInstance) : false
  );

  useEffect(() => {
    (async () => {
      await Promise.all([fetchInferenceInstance(), fetchDashboards()]);
    })();
  }, [fetchInferenceInstance, fetchDashboards]);

  const serviceName = useMemo(() => {
    if (dashboards.length > 0) {
      return dashboards[0].query_params["var-service"] || null;
    }
    return null;
  }, [dashboards]);

  const handleTabChange = (value: string) => {
    setActiveTab(value);
    setNow(Date.now());
    router.push(`/models/endpoints/${params.id}?tab=${value}`, {
      scroll: false,
    });
  };

  const handleDelete = async () => {
    await modelService.deleteInferenceInstance(params.id);
  };

  const timeRangeParams = useMemo(() => {
    const from = now - selectedTimeRange.value;
    return { from: from.toString(), to: now.toString() };
  }, [now, selectedTimeRange]);

  if (loading) {
    return <DetailSkeleton />;
  }

  if (!inferenceInstance) {
    return <NotFoundOrError error={loadError} noun="model instance" />;
  }

  return (
    <Tabs value={activeTab} onValueChange={handleTabChange} className="w-full">
      <TabsList
        className={`grid w-full ${
          inferenceInstance.config.enable_tracing
            ? "grid-cols-5"
            : "grid-cols-4"
        }`}
      >
        <TabsTrigger value="details">Details</TabsTrigger>
        <TabsTrigger value="logs">Logs</TabsTrigger>
        <TabsTrigger value="events">Events</TabsTrigger>
        <TabsTrigger value="dashboards">Dashboards</TabsTrigger>
        {inferenceInstance.config.enable_tracing && (
          <TabsTrigger value="tracing">Tracing</TabsTrigger>
        )}
      </TabsList>
      <TabsContent value="details">
        <DisplayCard
          title={inferenceInstance.model.name}
          description={`ID: ${inferenceInstance.id}`}
          icon={GetModelIcon(inferenceInstance.model.modelId)}
          onRefresh={fetchInferenceInstance}
          content={
            <div className="grid gap-4">
              <ErrorBanner
                error={inferenceInstance.last_error}
                at={inferenceInstance.last_error_at}
              />
              <DetailRow label="Model">
                {inferenceInstance.model.name || "N/A"}
              </DetailRow>
              <DetailRow label="Engine">
                {inferenceInstance.engine.name || "N/A"}
              </DetailRow>
              {inferenceInstance.host && (
                <DetailRow label="Host">
                  {inferenceInstance.host || "N/A"}
                </DetailRow>
              )}
              <DetailRow label="Ready">
                {inferenceInstance.ready ? "Yes" : "No"}
              </DetailRow>
              <DetailRow label="Status">
                <StatusBadge
                  ready={inferenceInstance.ready}
                  status={inferenceInstance.status}
                />
              </DetailRow>
              <DetailRow label="Replicas">
                {inferenceInstance.replicas ?? 1}
              </DetailRow>
              <DetailRow label="Resources">
                {[
                  inferenceInstance.engine.cpu
                    ? null
                    : `${inferenceInstance.gpu_count ?? 1} GPU`,
                  inferenceInstance.cpu ? `CPU ${inferenceInstance.cpu}` : null,
                  inferenceInstance.memory
                    ? `memory ${inferenceInstance.memory}`
                    : null,
                ]
                  .filter(Boolean)
                  .join(", ") || "defaults"}
              </DetailRow>
              {/* There is no separate Endpoint row: Access shows the same
                  host as a copyable Base URL, on the tab that opens by
                  default, and Ready and Status above already carry the
                  readiness its red/green text was repeating.

                  Not gated on the endpoint either: the key exists from
                  the moment the row is created, and gating this was what
                  made it unreachable while an instance was still
                  starting, or on a cluster with no gateway at all. */}
              <div className="grid grid-cols-2 items-start gap-4">
                <Label>Access</Label>
                <InstanceAccess
                  endpoint={inferenceInstance.endpoint}
                  model={upstreamModel(inferenceInstance)}
                  litellmModelName={
                    inferenceInstance.litellm_model_name ?? null
                  }
                  onShowApiKey={() => handleShowApiKey(false)}
                  apiKeyLoading={credentialLoading}
                />
              </div>
              <DetailRow
                label="Actions"
                valueClassName="flex items-center gap-2"
              >
                {inferenceInstance.ready && (
                  <Button asChild variant="outline" size="sm">
                    <Link
                      href={`/chat?target=${
                        inferenceInstance.litellm_model_name ??
                        `inst-${inferenceInstance.id.replace(/-/g, "").slice(-8)}`
                      }`}
                    >
                      Chat
                    </Link>
                  </Button>
                )}
                <Button asChild variant="outline" size="sm">
                  <Link href="/usage">Usage</Link>
                </Button>
              </DetailRow>
              <DetailRow label="Health Endpoint">
                {inferenceInstance.healthEndpoint || "N/A"}
              </DetailRow>
              <DetailRow label="Metrics Endpoint">
                {inferenceInstance.metricsEndpoint || "N/A"}
              </DetailRow>
              <DetailRow label="Tracing">
                {inferenceInstance.config.enable_tracing
                  ? "Enabled"
                  : "Disabled"}
              </DetailRow>
              {inferenceInstance.config.lora_adapters.length > 0 && (
                <DetailRow label="Adapters">
                  {inferenceInstance.config.lora_adapters.map((adapter) => (
                    <Button
                      key={adapter.id}
                      variant="outline"
                      className="px-2 py-1 bg-purple-100 text-purple-800 rounded-full text-sm mr-2 mb-2"
                      onClick={() => setSelectedAdapter(adapter)}
                    >
                      {adapter.name}
                    </Button>
                  ))}
                </DetailRow>
              )}
            </div>
          }
          footer={
            <div className="flex flex-wrap gap-2">
              <InstanceActions
                status={inferenceInstance.status}
                replicas={inferenceInstance.replicas ?? 1}
                onRestart={() =>
                  modelService.restartInferenceInstance(params.id)
                }
                onStop={() => modelService.stopInferenceInstance(params.id)}
                onResume={() => modelService.resumeInferenceInstance(params.id)}
                onScale={(replicas) =>
                  modelService.scaleInferenceInstance(params.id, replicas)
                }
                onDone={fetchInferenceInstance}
              />
              <DeleteButton
                onDelete={handleDelete}
                onSuccess={() => router.push("/models/endpoints")}
              />
            </div>
          }
        />
      </TabsContent>
      <InspectionTabs fetchLogs={fetchLogs} fetchEvents={fetchEvents} />
      <TabsContent value="dashboards">
        <Card>
          <CardHeader>
            <CardTitle>Dashboards</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="mb-4">
              <Combobox
                label={selectedTimeRange.label}
                placeholder="Search time range..."
                items={timeRangeItems}
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {dashboards.map((dashboard) => (
                <GrafanaEmbed
                  key={dashboard.id}
                  dashboardID={dashboard.dashboard_id || ""}
                  panelID={dashboard.panel_id || ""}
                  orgID={dashboard.org_id}
                  queryParams={{
                    ...dashboard.query_params,
                    ...timeRangeParams,
                  }}
                />
              ))}
            </div>
          </CardContent>
        </Card>
      </TabsContent>
      <TabsContent value="tracing">
        <Card>
          <CardHeader>
            <CardTitle>Traces</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-row items-center space-x-6">
              <Combobox
                label={selectedTimeRange.label}
                placeholder="Search time range..."
                items={timeRangeItems}
              />
              <div className="flex flex-row items-center space-x-2">
                <Label htmlFor="jaeger-limit" className="mb-1">
                  Limit
                </Label>
                <Input
                  id="jaeger-limit"
                  type="number"
                  value={jaegerLimit}
                  onChange={(e) => setJaegerLimit(Number(e.target.value))}
                  min={1}
                  max={1000}
                  className="w-[100px]"
                />
              </div>
            </div>
            {serviceName && (
              <JaegerEmbed
                serviceName={serviceName}
                start={now - selectedTimeRange.value}
                end={now}
                limit={jaegerLimit}
                lookback={
                  (selectedTimeRange.value / (60 * 1000)).toString() + "m"
                }
              />
            )}
          </CardContent>
        </Card>
      </TabsContent>
      <Dialog
        open={!!selectedAdapter}
        onOpenChange={() => setSelectedAdapter(null)}
      >
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{selectedAdapter?.name} Details</DialogTitle>
          </DialogHeader>
          <ScrollArea className="max-h-[60vh] mt-4">
            {selectedAdapter && (
              <div className="grid gap-4">
                {Object.entries(selectedAdapter).map(([key, value]) => (
                  <div key={key} className="grid grid-cols-2 items-start gap-4">
                    <Label className="font-medium">{key}</Label>
                    <span className="text-sm">
                      {typeof value === "object"
                        ? JSON.stringify(value, null, 2)
                        : String(value)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
        </DialogContent>
      </Dialog>
      <Dialog
        open={credentialDialogOpen}
        onOpenChange={setCredentialDialogOpen}
      >
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>Model instance API key</DialogTitle>
          </DialogHeader>
          {credential?.value ? (
            <div className="grid gap-4">
              <div className="flex items-center gap-2">
                <Input
                  readOnly
                  value={credential.value}
                  className="font-mono"
                />
                <CopyButton label="API key" text={credential.value || ""} />
              </div>
              <p className="text-sm text-muted-foreground">
                This key is shown only once. Copy it now — admins can view it
                again with <code>?reveal=true</code>.
              </p>
            </div>
          ) : (
            <div className="grid gap-4">
              <p className="text-sm text-muted-foreground">
                This key was already shown
                {credential?.shown_at
                  ? ` on ${new Date(credential.shown_at).toLocaleString()}`
                  : ""}
                . Admins can reveal it again.
              </p>
              <Button
                variant="outline"
                loading={credentialLoading}
                onClick={() => handleShowApiKey(true)}
              >
                Reveal again (admin)
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </Tabs>
  );
}
