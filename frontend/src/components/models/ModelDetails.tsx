"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  Pencil2Icon,
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
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
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
import { modelService } from "@/services/modelService";
import { useToast } from "@/components/hooks/use-toast";
import { DeleteButton } from "@/components/DeleteButton";
import { GetModelIcon, parseApiError } from "@/lib/utils";
import { DisplayCard } from "@/components/ui/DisplayCard";
import { DetailSkeleton } from "@/components/LoadingState";
import { CopyButton } from "@/components/CopyButton";

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
  const [error] = useState<string | null>(null);
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
  const [selectedJobLogs, setSelectedJobLogs] = useState<string | null>(null);
  const { toast } = useToast();

  const fetchAdapters = useCallback(async () => {
    try {
      const data = await modelService.getAdapters(params.id);
      setAdapters(data);
    } catch (error) {
      toast(parseApiError(error));
    }
  }, [params.id, toast]);

  useEffect(() => {
    const fetchModelDetails = async () => {
      try {
        const data = await modelService.getModelById(params.id);
        setModel(data);
      } catch (error) {
        toast(parseApiError(error));
      } finally {
        setLoading(false);
      }
    };

    const fetchFineTuneJobs = async () => {
      try {
        const data = await modelService.getFineTuneJobs(params.id);
        setFineTuneJobs(
          data.sort(
            (a, b) =>
              new Date(b.created_at).getTime() -
              new Date(a.created_at).getTime()
          )
        );
      } catch (error) {
        toast(parseApiError(error));
      }
    };

    (async () => {
      await fetchModelDetails();
      await fetchAdapters();
      await fetchFineTuneJobs();
    })();
  }, [params.id, toast, fetchAdapters]);

  const handleTabChange = (value: string) => {
    setActiveTab(value);
    router.push(`/models/${params.id}?tab=${value}`, { scroll: false });
  };

  const handleLaunchModel = () => {
    router.push(`/models/launch/${params.id}`);
  };

  const handleCreateAdapter = async () => {
    try {
      await modelService.createAdapter(params.id, {
        name: newAdapterName,
        path: newAdapterPath,
        hf_id: newAdapterHfId,
      });
      const updatedAdapters = await modelService.getAdapters(params.id);
      setAdapters(updatedAdapters);
      setNewAdapterName("");
      setNewAdapterHfId("");
      setNewAdapterPath("");
      setIsImportDialogOpen(false);
      toast({
        title: "Success",
        description: "Adapter created successfully",
        variant: "success",
      });
    } catch (error) {
      toast(parseApiError(error));
    }
  };

  const handleDeleteAdapter = async (adapterId: string) => {
    await modelService.deleteAdapter(params.id, adapterId);
  };

  const handleEditAdapter = (adapter: Adapter) => {
    setEditingAdapter(adapter);
    setIsEditDialogOpen(true);
  };

  const handleUpdateAdapter = async () => {
    if (!editingAdapter) return;

    try {
      await modelService.updateAdapter(params.id, editingAdapter.id, {
        name: editingAdapter.name,
        hf_id: editingAdapter.hf_id,
        path: editingAdapter.path || "",
      });
      const updatedAdapters = await modelService.getAdapters(params.id);
      setAdapters(updatedAdapters);
      setIsEditDialogOpen(false);
      setEditingAdapter(null);
      toast({
        title: "Success",
        description: "Adapter updated successfully",
        variant: "success",
      });
    } catch (error) {
      toast(parseApiError(error));
    }
  };

  const handleViewParams = (params: Record<string, unknown>) => {
    setSelectedJobParams(yaml.stringify(params, null, 2));
    setIsViewParamsDialogOpen(true);
  };

  const handleViewLogs = async (jobId: string) => {
    setIsViewLogsDialogOpen(true);
    setSelectedJobLogs(null);
    try {
      const logs = await modelService.getFineTuneJobLogs(params.id, jobId);
      setSelectedJobLogs(logs);
    } catch (error) {
      setIsViewLogsDialogOpen(false);
      toast(parseApiError(error));
    }
  };

  const handleDeleteFineTuneJob = async (jobId: string) => {
    await modelService.deleteFineTuneJob(params.id, jobId);
  };

  if (loading) {
    return <DetailSkeleton />;
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
        <DisplayCard
          title={model.name}
          icon={GetModelIcon(model.modelId)}
          content={
            <div className="grid gap-4">
              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Name</Label>
                <span>{model.name}</span>
              </div>
              <div className="grid grid-cols-2 items-center gap-4">
                <Label>Model ID</Label>
                <span className="flex items-center gap-2">
                  {model.modelId}
                  <CopyButton label="model id" text={model.modelId} size="sm" />
                </span>
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
                <span>{model.size ? formatSize(model.size) : "unknown"}</span>
              </div>
            </div>
          }
          footer={
            <div className="flex justify-between space-x-8">
              <Button
                onClick={handleLaunchModel}
                icon={<RocketIcon className="mr-2 w-4 h-4" />}
              >
                Launch Model
              </Button>
              <Link href={`/models/${model.id}/finetune`} passHref>
                <Button
                  variant="secondary"
                  icon={<HandIcon className="mr-2 w-4 h-4" />}
                >
                  Fine-tune
                </Button>
              </Link>
            </div>
          }
        />
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
                {adapters.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className="text-center text-muted-foreground"
                    >
                      No adapters yet
                    </TableCell>
                  </TableRow>
                ) : (
                  adapters.map((adapter) => (
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
                          icon={<Pencil2Icon className="h-4 w-4" />}
                        ></Button>
                        <DeleteButton
                          buttonText=""
                          onDelete={() => handleDeleteAdapter(adapter.id)}
                          onSuccess={() => fetchAdapters()}
                        />
                      </TableCell>
                    </TableRow>
                  ))
                )}
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
                <Button icon={<HandIcon className="mr-2 w-4 h-4" />}>
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
                {fineTuneJobs.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={7}
                      className="text-center text-muted-foreground"
                    >
                      No fine-tune jobs yet
                    </TableCell>
                  </TableRow>
                ) : (
                  fineTuneJobs.map((job) => (
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
                          icon={<EyeOpenIcon className="mr-2 h-4 w-4" />}
                        ></Button>
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="outline"
                          size="sm"
                          className="mr-2"
                          onClick={() => handleViewLogs(job.id)}
                          icon={<FileTextIcon className="mr-2 h-4 w-4" />}
                        ></Button>
                      </TableCell>
                      <TableCell>
                        {new Date(job.created_at).toLocaleString()}
                      </TableCell>
                      <TableCell>
                        <DeleteButton
                          buttonText=""
                          onDelete={() => handleDeleteFineTuneJob(job.id)}
                          onSuccess={() =>
                            setFineTuneJobs(
                              fineTuneJobs.filter((jobs) => jobs.id !== job.id)
                            )
                          }
                        />
                      </TableCell>
                    </TableRow>
                  ))
                )}
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
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words bg-gray-100 p-4 rounded text-sm">
            {selectedJobLogs === null
              ? "Loading logs..."
              : selectedJobLogs || "No logs yet."}
          </pre>
        </DialogContent>
      </Dialog>
    </Tabs>
  );
}
