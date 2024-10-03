"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  Pencil2Icon,
  TrashIcon,
  PlusIcon,
  RocketIcon,
  HandIcon,
  EyeOpenIcon,
  FileTextIcon,
} from "@radix-ui/react-icons";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Model, Adapter, FineTuneJob } from "@/types/models";
import Link from "next/link";
import yaml from "yaml";

function formatSize(bytes: number): string {
  const MB = 1024 * 1024;
  const GB = MB * 1024;
  if (bytes >= GB) {
    return `${(bytes / GB).toFixed(2)} GB`;
  } else {
    return `${(bytes / MB).toFixed(2)} MB`;
  }
}

export default function ModelDetails({ params }: { params: { id: string } }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [model, setModel] = useState<Model | null>(null);
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isImportDialogOpen, setIsImportDialogOpen] = useState(false);
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false);
  const [newAdapterName, setNewAdapterName] = useState("");
  const [newAdapterHfId, setNewAdapterHfId] = useState("");
  const [newAdapterPath, setNewAdapterPath] = useState("");
  const [editingAdapter, setEditingAdapter] = useState<Adapter | null>(null);
  const [activeTab, setActiveTab] = useState(
    searchParams.get("tab") || "details"
  );
  const [fineTuneJobs, setFineTuneJobs] = useState<FineTuneJob[]>([]);
  const [isViewParamsDialogOpen, setIsViewParamsDialogOpen] = useState(false);
  const [isViewLogsDialogOpen, setIsViewLogsDialogOpen] = useState(false);
  const [selectedJobParams, setSelectedJobParams] = useState<string>("");
  const [selectedJobLogs, setSelectedJobLogs] = useState<string>("");

  useEffect(() => {
    const fetchModelDetails = async () => {
      try {
        const response = await fetch(`/api/v1alpha1/models/${params.id}`);
        if (!response.ok) {
          throw new Error("Failed to fetch model details");
        }
        const data = await response.json();
        setModel(data);
        setLoading(false);
      } catch (error) {
        console.error("Error fetching model details:", error);
        setError("Failed to load model details");
        setLoading(false);
      }
    };

    const fetchAdapters = async () => {
      try {
        const response = await fetch(
          `/api/v1alpha1/model/${params.id}/adapters`
        );
        if (!response.ok) {
          throw new Error("Failed to fetch adapters");
        }
        const data = await response.json();
        setAdapters(data);
      } catch (error) {
        console.error("Error fetching adapters:", error);
        setError("Failed to load adapters");
      }
    };

    const fetchFineTuneJobs = async () => {
      try {
        const response = await fetch(
          `/api/v1alpha1/models/${params.id}/finetune`
        );
        if (!response.ok) {
          throw new Error("Failed to fetch fine-tune jobs");
        }
        const data = await response.json();
        setFineTuneJobs(
          data.sort(
            (a: FineTuneJob, b: FineTuneJob) =>
              new Date(b.created_at).getTime() -
              new Date(a.created_at).getTime()
          )
        );
      } catch (error) {
        console.error("Error fetching fine-tune jobs:", error);
        setError("Failed to load fine-tune jobs");
      }
    };

    fetchModelDetails();
    fetchAdapters();
    fetchFineTuneJobs();
  }, [params.id]);

  const handleTabChange = (value: string) => {
    setActiveTab(value);
    router.push(`/models/${params.id}?tab=${value}`, { scroll: false });
  };

  const handleLaunchModel = () => {
    router.push(`/models/launch/${params.id}`);
  };

  const handleCreateAdapter = async () => {
    try {
      const response = await fetch(
        `/api/v1alpha1/model/${params.id}/adapters`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            name: newAdapterName,
            path: newAdapterPath,
            hf_id: newAdapterHfId,
            base_model: {
              id: model?.id,
            },
          }),
        }
      );

      if (!response.ok) {
        throw new Error("Failed to create adapter");
      }

      // Refresh the adapters list
      const updatedAdapters = await fetch(
        `/api/v1alpha1/model/${params.id}/adapters`
      ).then((res) => res.json());
      setAdapters(updatedAdapters);

      // Reset form fields and close dialog
      setNewAdapterName("");
      setNewAdapterHfId("");
      setNewAdapterPath("");
      setIsImportDialogOpen(false);
    } catch (error) {
      console.error("Error creating adapter:", error);
      setError("Failed to create adapter");
    }
  };

  const handleDeleteAdapter = async (adapterId: string) => {
    try {
      const response = await fetch(
        `/api/v1alpha1/model/${params.id}/adapters/${adapterId}`,
        {
          method: "DELETE",
        }
      );

      if (!response.ok) {
        throw new Error("Failed to delete adapter");
      }

      // Refresh the adapters list
      const updatedAdapters = await fetch(
        `/api/v1alpha1/model/${params.id}/adapters`
      ).then((res) => res.json());
      setAdapters(updatedAdapters);
    } catch (error) {
      console.error("Error deleting adapter:", error);
      setError("Failed to delete adapter");
    }
  };

  const handleEditAdapter = (adapter: Adapter) => {
    setEditingAdapter(adapter);
    setIsEditDialogOpen(true);
  };

  const handleUpdateAdapter = async () => {
    if (!editingAdapter) return;

    try {
      const response = await fetch(
        `/api/v1alpha1/model/${params.id}/adapters/${editingAdapter.id}`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            name: editingAdapter.name,
            hf_id: editingAdapter.hf_id,
            path: editingAdapter.path,
            base_model: {
              id: model?.id,
            },
          }),
        }
      );

      if (!response.ok) {
        throw new Error("Failed to update adapter");
      }

      // Refresh the adapters list
      const updatedAdapters = await fetch(
        `/api/v1alpha1/model/${params.id}/adapters`
      ).then((res) => res.json());
      setAdapters(updatedAdapters);

      // Close the edit dialog
      setIsEditDialogOpen(false);
      setEditingAdapter(null);
    } catch (error) {
      console.error("Error updating adapter:", error);
      setError("Failed to update adapter");
    }
  };

  const handleViewParams = (params: Record<string, any>) => {
    setSelectedJobParams(yaml.stringify(params, null, 2));
    setIsViewParamsDialogOpen(true);
  };

  const handleViewLogs = async (jobId: string) => {
    try {
      const response = await fetch(
        `/api/v1alpha1/models/${params.id}/finetune/${jobId}/logs`
      );
      if (!response.ok) {
        throw new Error("Failed to fetch logs");
      }
      const logs = await response.text();
      setSelectedJobLogs(logs);
      setIsViewLogsDialogOpen(true);
    } catch (error) {
      console.error("Error fetching logs:", error);
      setError("Failed to load logs");
    }
  };

  const handleDeleteFineTuneJob = async (jobId: string) => {
    if (confirm("Are you sure you want to delete this fine-tune job?")) {
      try {
        const response = await fetch(
          `/api/v1alpha1/models/${params.id}/finetune/${jobId}`,
          {
            method: "DELETE",
          }
        );
        if (!response.ok) {
          throw new Error("Failed to delete fine-tune job");
        }
        setFineTuneJobs(fineTuneJobs.filter((job) => job.id !== jobId));
      } catch (error) {
        console.error("Error deleting fine-tune job:", error);
        setError("Failed to delete fine-tune job");
      }
    }
  };

  if (loading) {
    return <div>Loading...</div>;
  }

  if (error) {
    return <div>Error: {error}</div>;
  }

  if (!model) {
    return <div>No model found</div>;
  }

  return (
    <Tabs value={activeTab} onValueChange={handleTabChange} className="w-full">
      <TabsList className="grid w-full grid-cols-3">
        <TabsTrigger value="details">Details</TabsTrigger>
        <TabsTrigger value="adapters">Adapters</TabsTrigger>
        <TabsTrigger value="finetune">Fine-tune Jobs</TabsTrigger>
      </TabsList>
      <TabsContent value="details">
        <Card>
          <CardHeader>
            <CardTitle>{model.name}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4">
              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Name</Label>
                <span>{model.name}</span>
              </div>
              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Model ID</Label>
                <span>{model.modelId}</span>
              </div>
              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Description</Label>
                <span>{model.description}</span>
              </div>
              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Category</Label>
                <span>{model.category}</span>
              </div>
              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Subcategory</Label>
                <span>{model.subcategory}</span>
              </div>
              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Size</Label>
                <span>{formatSize(model.size)}</span>
              </div>
            </div>
          </CardContent>
          <CardFooter>
            <div className="flex justify-between space-x-8">
              <Button onClick={handleLaunchModel}>
                <RocketIcon className="mr-2 h-4 w-4" />
                Launch Model
              </Button>
              <Link href={`/models/${model.id}/finetune`} passHref>
                <Button variant="secondary">
                  <HandIcon className="mr-2 w-4 h-4" />
                  Fine-tune
                </Button>
              </Link>
            </div>
          </CardFooter>
        </Card>
      </TabsContent>
      <TabsContent value="adapters">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Adapters</CardTitle>
            <Dialog
              open={isImportDialogOpen}
              onOpenChange={setIsImportDialogOpen}
            >
              <DialogTrigger asChild>
                <Button>
                  <PlusIcon className="mr-2 h-4 w-4" />
                  Import Adapter
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Import Adapter</DialogTitle>
                  <DialogDescription>
                    Enter the details for the new adapter.
                  </DialogDescription>
                </DialogHeader>
                <div className="space-y-4">
                  <Input
                    placeholder="Adapter Name"
                    value={newAdapterName}
                    onChange={(e) => setNewAdapterName(e.target.value)}
                  />
                  <Input
                    placeholder="Huggingface ID"
                    value={newAdapterHfId}
                    onChange={(e) => setNewAdapterHfId(e.target.value)}
                  />
                  <Input
                    placeholder="Path to adapter"
                    value={newAdapterPath}
                    onChange={(e) => setNewAdapterPath(e.target.value)}
                  />
                </div>
                <DialogFooter>
                  <Button onClick={handleCreateAdapter}>Create Adapter</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Huggingface ID</TableHead>
                  <TableHead>Path</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {adapters.map((adapter) => (
                  <TableRow key={adapter.id}>
                    <TableCell>{adapter.id}</TableCell>
                    <TableCell>{adapter.name}</TableCell>
                    <TableCell>
                      <a
                        href={`https://huggingface.co/${adapter.hf_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-500 hover:text-blue-600"
                      >
                        {adapter.hf_id}
                      </a>
                    </TableCell>
                    <TableCell>{adapter.path}</TableCell>
                    <TableCell>
                      <Button
                        variant="outline"
                        size="sm"
                        className="mr-2"
                        onClick={() => handleEditAdapter(adapter)}
                      >
                        <Pencil2Icon className="h-4 w-4" />
                      </Button>
                      <Dialog>
                        <DialogTrigger asChild>
                          <Button variant="outline" size="sm">
                            <TrashIcon className="h-4 w-4" />
                          </Button>
                        </DialogTrigger>
                        <DialogContent>
                          <DialogHeader>
                            <DialogTitle>
                              Are you sure you want to delete this adapter?
                            </DialogTitle>
                            <DialogDescription>
                              This action cannot be undone.
                            </DialogDescription>
                          </DialogHeader>
                          <DialogFooter>
                            <Button
                              variant="destructive"
                              onClick={() => handleDeleteAdapter(adapter.id)}
                            >
                              Delete
                            </Button>
                          </DialogFooter>
                        </DialogContent>
                      </Dialog>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </TabsContent>
      <TabsContent value="finetune">
        <Card>
          <CardHeader>
            <CardTitle>Fine-tune Jobs</CardTitle>
            <div className="flex justify-end">
              <Link href={`/models/${model.id}/finetune`} passHref>
                <Button>
                  <HandIcon className="mr-2 w-4 h-4" />
                  Fine-tune
                </Button>
              </Link>
            </div>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Params</TableHead>
                  <TableHead>Logs</TableHead>
                  <TableHead>Created At</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {fineTuneJobs.map((job) => (
                  <TableRow key={job.id}>
                    <TableCell>{job.id}</TableCell>
                    <TableCell>{job.name}</TableCell>
                    <TableCell>{job.status}</TableCell>
                    <TableCell>
                      <Button
                        variant="outline"
                        size="sm"
                        className="mr-2"
                        onClick={() => handleViewParams(job.params)}
                      >
                        <EyeOpenIcon className="mr-2 h-4 w-4" />
                      </Button>
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="outline"
                        size="sm"
                        className="mr-2"
                        onClick={() => handleViewLogs(job.id)}
                      >
                        <FileTextIcon className="mr-2 h-4 w-4" />
                      </Button>
                    </TableCell>
                    <TableCell>
                      {new Date(job.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleDeleteFineTuneJob(job.id)}
                      >
                        <TrashIcon className="mr-2 h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </TabsContent>

      {/* Edit Adapter Dialog */}
      <Dialog open={isEditDialogOpen} onOpenChange={setIsEditDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Adapter</DialogTitle>
            <DialogDescription>
              Update the details for this adapter.
            </DialogDescription>
          </DialogHeader>
          {editingAdapter && (
            <div className="space-y-4">
              <div>
                <Label htmlFor="edit-adapter-name">Name</Label>
                <Input
                  id="edit-adapter-name"
                  value={editingAdapter.name}
                  onChange={(e) =>
                    setEditingAdapter({
                      ...editingAdapter,
                      name: e.target.value,
                    })
                  }
                />
              </div>
              <div>
                <Label htmlFor="edit-adapter-hf-id">Huggingface ID</Label>
                <Input
                  id="edit-adapter-hf-id"
                  value={editingAdapter.hf_id}
                  onChange={(e) =>
                    setEditingAdapter({
                      ...editingAdapter,
                      hf_id: e.target.value,
                    })
                  }
                />
              </div>
              <div>
                <Label htmlFor="edit-adapter-path">Path</Label>
                <Input
                  id="edit-adapter-path"
                  value={editingAdapter.path || ""}
                  onChange={(e) =>
                    setEditingAdapter({
                      ...editingAdapter,
                      path: e.target.value,
                    })
                  }
                />
              </div>
            </div>
          )}
          <DialogFooter>
            <Button onClick={handleUpdateAdapter}>Update Adapter</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* View Params Dialog */}
      <Dialog
        open={isViewParamsDialogOpen}
        onOpenChange={setIsViewParamsDialogOpen}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Fine-tune Job Parameters</DialogTitle>
          </DialogHeader>
          <pre className="max-h-96 overflow-auto bg-gray-100 p-4 rounded">
            {selectedJobParams}
          </pre>
        </DialogContent>
      </Dialog>

      {/* View Logs Dialog */}
      <Dialog
        open={isViewLogsDialogOpen}
        onOpenChange={setIsViewLogsDialogOpen}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Fine-tune Job Logs</DialogTitle>
          </DialogHeader>
          <pre className="max-h-96 overflow-auto bg-gray-100 p-4 rounded">
            {selectedJobLogs}
          </pre>
        </DialogContent>
      </Dialog>
    </Tabs>
  );
}
