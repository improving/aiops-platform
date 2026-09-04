"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  ChevronDownIcon,
  ClipboardCopyIcon,
  OpenInNewWindowIcon,
} from "@radix-ui/react-icons";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import GrafanaEmbed from "@/components/GrafanaEmbed";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Adapter,
  InferenceInstance,
  InferenceInstanceDashboard,
} from "@/types/models";
import JaegerEmbed from "@/components/JaegerEmbed";
import { Input } from "@/components/ui/input";
import { GRAFANA_URL, JAEGER_URL } from "@/constants";
import { modelService } from "@/services/modelService";
import { useToast } from "@/components/hooks/use-toast";
import { DeleteButton } from "@/components/DeleteButton";
import {
  Command,
  CommandGroup,
  CommandItem,
  CommandInput,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { CommandList } from "@/components/ui/command";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { GetModelIcon, parseApiError } from "@/lib/utils";
import { DisplayCard } from "@/components/ui/DisplayCard";
import { RefreshButton } from "../RefreshButton";

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
  const [dashboards, setDashboards] = useState<InferenceInstanceDashboard[]>(
    []
  );
  const [selectedTimeRange, setSelectedTimeRange] = useState(
    timeRangeOptions[0]
  );
  const [open, setOpen] = useState(false);
  const [activeTab, setActiveTab] = useState(
    searchParams.get("tab") || "details"
  );
  const [selectedAdapter, setSelectedAdapter] = useState<Adapter | null>(null);
  const [serviceName, setServiceName] = useState<string | null>(null);
  const [jaegerLimit, setJaegerLimit] = useState(20);
  const { toast } = useToast();

  const fetchInferenceInstance = useCallback(async () => {
    try {
      const data = await modelService.getInferenceInstance(params.id);
      setInferenceInstance(data);
    } catch (error) {
      toast(parseApiError(error));
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

  useEffect(() => {
    fetchInferenceInstance();
    fetchDashboards();
  }, [fetchInferenceInstance, fetchDashboards]);

  useEffect(() => {
    if (dashboards.length > 0) {
      const serviceParam = dashboards[0].query_params["var-service"];
      if (serviceParam) {
        setServiceName(serviceParam);
      }
    }
  }, [dashboards]);

  const handleTabChange = (value: string) => {
    setActiveTab(value);
    router.push(`/models/endpoints/${params.id}?tab=${value}`, {
      scroll: false,
    });
  };

  const handleDelete = async () => {
    await modelService.deleteInferenceInstance(params.id);
  };

  const timeRangeParams = useMemo(() => {
    const to = Date.now();
    const from = to - selectedTimeRange.value;
    return { from: from.toString(), to: to.toString() };
  }, [selectedTimeRange]);

  if (loading) {
    return <div>Loading...</div>;
  }

  if (!inferenceInstance) {
    return <div>No inference instance found</div>;
  }

  return (
    <Tabs value={activeTab} onValueChange={handleTabChange} className="w-full">
      {inferenceInstance.config.enable_tracing ? (
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="details">Details</TabsTrigger>
          <TabsTrigger value="dashboards">Dashboards</TabsTrigger>
          <TabsTrigger value="tracing">Tracing</TabsTrigger>
        </TabsList>
      ) : (
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="details">Details</TabsTrigger>
          <TabsTrigger value="dashboards">Dashboards</TabsTrigger>
        </TabsList>
      )}
      <TabsContent value="details">
        <DisplayCard
          title={inferenceInstance.model.name}
          description={`ID: ${inferenceInstance.id}`}
          icon={GetModelIcon(inferenceInstance.model.modelId)}
          onRefresh={fetchInferenceInstance}
          content={
            <div className="grid gap-4">
              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Model</Label>
                <span>{inferenceInstance.model.name || "N/A"}</span>
              </div>
              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Engine</Label>
                <span>{inferenceInstance.engine.name || "N/A"}</span>
              </div>
              {inferenceInstance.host && (
                <div className="grid grid-cols-2 items-center gap-4">
                  <Label>Host</Label>
                  <span>{inferenceInstance.host || "N/A"}</span>
                </div>
              )}
              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Ready</Label>
                <span>{inferenceInstance.ready ? "Yes" : "No"}</span>
              </div>
              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Status</Label>
                <span>{inferenceInstance.status || "N/A"}</span>
              </div>
              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Endpoint</Label>
                <span className="flex items-center">
                  <span
                    className={
                      inferenceInstance.ready
                        ? "text-green-500"
                        : "text-red-500"
                    }
                  >
                    <OpenInNewWindowIcon className="w-4 h-4 inline-block" />
                    <a
                      href={`${inferenceInstance.endpoint}/docs`}
                      target="_blank"
                    >
                      {inferenceInstance.endpoint || "N/A"}
                    </a>
                  </span>
                  <Button
                    variant="outline"
                    onClick={() =>
                      navigator.clipboard.writeText(
                        inferenceInstance.endpoint || ""
                      )
                    }
                    className="ml-2"
                    icon={<ClipboardCopyIcon className="w-4 h-4" />}
                  ></Button>
                </span>
              </div>
              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Health Endpoint</Label>
                <span>{inferenceInstance.healthEndpoint || "N/A"}</span>
              </div>
              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Metrics Endpoint</Label>
                <span>{inferenceInstance.metricsEndpoint || "N/A"}</span>
              </div>

              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Tracing</Label>
                <span>
                  {inferenceInstance.config.enable_tracing
                    ? "Enabled"
                    : "Disabled"}
                </span>
              </div>

              {inferenceInstance.config.lora_adapters.length > 0 && (
                <div className="grid grid-cols-2 items-center gap-4">
                  <Label>Adapters</Label>
                  <span>
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
                  </span>
                </div>
              )}
            </div>
          }
          footer={
            <DeleteButton
              onDelete={handleDelete}
              onSuccess={() => router.push("/models/endpoints")}
            />
          }
        />
      </TabsContent>
      <TabsContent value="dashboards">
        <Card>
          <CardHeader>
            <CardTitle>Dashboards</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="mb-4">
              <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger asChild>
                  <Button
                    variant="outline"
                    role="combobox"
                    aria-expanded={open}
                    className="w-[200px] justify-between"
                  >
                    {selectedTimeRange.label}
                    <ChevronDownIcon className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-[200px] p-0">
                  <Command>
                    <CommandInput
                      placeholder="Search time range..."
                      className="h-9"
                    />
                    <CommandList>
                      <CommandGroup>
                        {timeRangeOptions.map((option) => (
                          <CommandItem
                            key={option.value}
                            value={option.value.toString()}
                            onSelect={() => {
                              setSelectedTimeRange(option);
                              setOpen(false);
                            }}
                          >
                            {option.label}
                          </CommandItem>
                        ))}
                      </CommandGroup>
                    </CommandList>
                  </Command>
                </PopoverContent>
              </Popover>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {dashboards.map((dashboard) => (
                <GrafanaEmbed
                  key={dashboard.id}
                  grafanaEndpoint={GRAFANA_URL}
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
              <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger asChild>
                  <Button
                    variant="outline"
                    role="combobox"
                    aria-expanded={open}
                    className="w-[200px] justify-between"
                  >
                    {selectedTimeRange.label}
                    <ChevronDownIcon className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-[200px] p-0">
                  <Command>
                    <CommandInput
                      placeholder="Search time range..."
                      className="h-9"
                    />
                    <CommandList>
                      <CommandGroup>
                        {timeRangeOptions.map((option) => (
                          <CommandItem
                            key={option.value}
                            value={option.value.toString()}
                            onSelect={() => {
                              setSelectedTimeRange(option);
                              setOpen(false);
                            }}
                          >
                            {option.label}
                          </CommandItem>
                        ))}
                      </CommandGroup>
                    </CommandList>
                  </Command>
                </PopoverContent>
              </Popover>
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
                jaegerEndpoint={JAEGER_URL}
                serviceName={serviceName}
                start={Date.now() - selectedTimeRange.value}
                end={Date.now()}
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
    </Tabs>
  );
}
