"use client";

import { useState, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { TrashIcon, ClipboardCopyIcon } from "@radix-ui/react-icons";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardFooter,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import GrafanaEmbed from "@/components/GrafanaEmbed";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
import { ChevronDownIcon } from "@radix-ui/react-icons";
import { CommandList } from "cmdk";
import { InferenceInstance, InferenceInstanceDashboard } from "@/types/models";

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
  const [inferenceInstance, setInferenceInstance] =
    useState<InferenceInstance | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dashboards, setDashboards] = useState<InferenceInstanceDashboard[]>(
    []
  );
  const [selectedTimeRange, setSelectedTimeRange] = useState(
    timeRangeOptions[0]
  );
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const fetchInferenceInstance = async () => {
      try {
        const response = await fetch(
          `/api/v1alpha1/inferenceInstance/${params.id}`
        );
        if (!response.ok) {
          throw new Error("Failed to fetch inference instance");
        }
        const data = await response.json();
        setInferenceInstance(data);
        setLoading(false);
      } catch (error) {
        console.error("Error fetching inference instance:", error);
        setError("Failed to load inference instance details");
        setLoading(false);
      }
    };
    fetchInferenceInstance();

    const fetchDashboards = async () => {
      try {
        const response = await fetch(
          `/api/v1alpha1/inferenceInstance/${params.id}/dashboards`
        );
        if (!response.ok) {
          throw new Error("Failed to fetch dashboards");
        }
        const data = await response.json();
        setDashboards(data);
      } catch (error) {
        console.error("Error fetching dashboards:", error);
        setError("Failed to load dashboards");
      }
    };
    fetchDashboards();
  }, [params.id]);

  const handleDelete = async () => {
    try {
      const response = await fetch(
        `/api/v1alpha1/inferenceInstance/${params.id}`,
        {
          method: "DELETE",
        }
      );
      if (!response.ok) {
        throw new Error("Failed to delete inference instance");
      }
      router.push("/models/endpoints");
    } catch (error) {
      console.error("Error deleting inference instance:", error);
      setError("Failed to delete inference instance");
    }
  };
  const timeRangeParams = useMemo(() => {
    const to = Date.now();
    const from = to - selectedTimeRange.value;
    return { from: from.toString(), to: to.toString() };
  }, [selectedTimeRange]);

  if (loading) {
    return <div>Loading...</div>;
  }

  if (error) {
    return <div>Error: {error}</div>;
  }

  if (!inferenceInstance) {
    return <div>No inference instance found</div>;
  }

  return (
    <Tabs defaultValue="details" className="w-full">
        <TabsList className="grid w-full grid-cols-2">
        <TabsTrigger value="details">Details</TabsTrigger>
        <TabsTrigger value="dashboards">Dashboards</TabsTrigger>
        </TabsList>
        <TabsContent value="details">
        <Card>
            <CardHeader>
            <CardTitle>{inferenceInstance.model.name}</CardTitle>
            </CardHeader>
            <CardContent>
            <div className="grid gap-4">
                <div className="grid grid-cols-2 items-center gap-4">
                <Label>Model</Label>
                <span>{inferenceInstance.model.name || "N/A"}</span>
                </div>
                <div className="grid grid-cols-2 items-center gap-4">
                <Label>Engine</Label>
                <span>{inferenceInstance.engine.name || "N/A"}</span>
                </div>
                <div className="grid grid-cols-2 items-center gap-4">
                <Label>Host</Label>
                <span>{inferenceInstance.host || "N/A"}</span>
                </div>
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
                    {inferenceInstance.ready ? (
                    <span className="text-green-500">
                        {inferenceInstance.endpoint || "N/A"}
                    </span>
                    ) : (
                    <span className="text-red-500">
                        {inferenceInstance.endpoint || "N/A"}
                    </span>
                    )}
                    <Button
                    variant="outline"
                    onClick={() =>
                        navigator.clipboard.writeText(
                        inferenceInstance.endpoint || ""
                        )
                    }
                    className="ml-2"
                    >
                    <ClipboardCopyIcon className="mr-2 w-4 h-4" />
                    </Button>
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
            </div>
            </CardContent>
            <CardFooter>
            <Dialog>
                <DialogTrigger asChild>
                <Button variant="destructive">
                    <TrashIcon className="mr-2 w-4 h-4" />
                    Delete Inference Endpoint
                </Button>
                </DialogTrigger>
                <DialogContent>
                <DialogHeader>
                    <DialogTitle>
                    Are you sure you want to delete this inference endpoint?
                    </DialogTitle>
                    <DialogDescription>
                    This action cannot be undone.
                    </DialogDescription>
                </DialogHeader>
                <DialogFooter>
                    <Button
                    type="button"
                    variant="destructive"
                    onClick={handleDelete}
                    >
                    <TrashIcon className="mr-2 w-4 h-4" />
                    Delete
                    </Button>
                </DialogFooter>
                </DialogContent>
            </Dialog>
            </CardFooter>
        </Card>
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
                    grafanaEndpoint={
                    process.env.NEXT_PUBLIC_GRAFANA_URL ||
                    "http://192.0.2.202"
                    }
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
    </Tabs>
  );
}
