"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
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

interface InferenceInstance {
  id: string;
  model: {
    id: string;
    name: string;
  };
  engine: {
    id: string;
    name: string;
  };
  host: string;
  endpoint: string;
  healthEndpoint: string;
  metricsEndpoint: string;
  ready: boolean;
  status: string;
}

interface GrafanaEmbedPanel {
  grafanaEndpoint: string;
  dashboardID: string;
  panelID: string;
  orgID: string;
  queryParams: {
    [key: string]: string;
  };
}

const mockGrafanaPanels: GrafanaEmbedPanel[] = [
  {
    grafanaEndpoint: "",
    dashboardID: "cds3su97jm1hce",
    panelID: "12",
    orgID: "1",
    queryParams: {},
  },
  {
    grafanaEndpoint: "",
    dashboardID: "cds3su97jm1hce",
    panelID: "14",
    orgID: "1",
    queryParams: {},
  },
  {
    grafanaEndpoint: "",
    dashboardID: "cds3su97jm1hce",
    panelID: "10",
    orgID: "1",
    queryParams: {},
  },
  {
    grafanaEndpoint: "",
    dashboardID: "cds3su97jm1hce",
    panelID: "16",
    orgID: "1",
    queryParams: {},
  },
];

export default function InferenceEndpointDetails({
  params,
}: {
  params: { id: string };
}) {
  const router = useRouter();
  const [inferenceInstance, setInferenceInstance] =
    useState<InferenceInstance | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [grafanaPanels, setGrafanaPanels] = useState<GrafanaEmbedPanel[]>([]);

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
      router.push("/inference-endpoints");
    } catch (error) {
      console.error("Error deleting inference instance:", error);
      setError("Failed to delete inference instance");
    }
  };

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
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-grow container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Inference Endpoint Details</h1>
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
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {mockGrafanaPanels.map((panel, index) => (
                    <GrafanaEmbed
                      key={index}
                      grafanaEndpoint={panel.grafanaEndpoint || process.env.GRAFANA_URL || ""} // Ensure a string fallback
                      dashboardID={panel.dashboardID}
                      panelID={panel.panelID}
                      orgID={panel.orgID}
                      queryParams={panel.queryParams}
                    />
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </main>
      <Footer />
    </div>
  );
}
