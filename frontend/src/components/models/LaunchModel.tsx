"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DesktopIcon,
  RocketIcon,
  ThickArrowRightIcon,
  ValueNoneIcon,
} from "@radix-ui/react-icons";
import { useToast } from "@/components/hooks/use-toast";
import { Adapter, Engine, Host, Model } from "@/types/models";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { modelService } from "@/services/modelService";
import { parseApiError } from "@/lib/utils";
import { DisplayCard } from "@/components/ui/DisplayCard";

const tabs = ["accelerators", "deployConfig", "envVars"];

type EnvVar = {
  name: string;
  value: string;
  editable: boolean;
  new: boolean;
  updated: boolean;
};
type CLIArg = {
  name: string;
  value: string;
  editable: boolean;
  new: boolean;
  updated: boolean;
};

export default function LaunchModel({ params }: { params: { id: string } }) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState("accelerators");
  const [formData, setFormData] = useState({
    hostId: "",
    engineId: "",
  });
  const [args, setArgs] = useState<CLIArg[]>([]);
  const [envVars, setEnvVars] = useState<EnvVar[]>([]);
  const [engines, setEngines] = useState<Engine[]>([]);
  const [hosts, setHosts] = useState<Host[]>([]);
  const [model, setModel] = useState<Model | null>(null);
  const [filteredEngines, setFilteredEngines] = useState<Engine[]>([]);
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [selectedAdapters, setSelectedAdapters] = useState<Adapter[]>([]);
  const { toast } = useToast(); // Initialize toast
  const [enableTracing, setEnableTracing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    const fetchEngines = async () => {
      try {
        const data = await modelService.getEngines();
        setEngines(data);
      } catch (error) {
        toast(parseApiError(error));
      }
    };
    const fetchHosts = async () => {
      try {
        const data = await modelService.getHosts();
        setHosts(data);
      } catch (error) {
        toast(parseApiError(error));
      }
    };
    const fetchModel = async () => {
      try {
        const data = await modelService.getModelById(params.id);
        setModel(data);
      } catch (error) {
        toast(parseApiError(error));
      }
    };
    const fetchAdapters = async () => {
      try {
        const data = await modelService.getAdapters(params.id);
        setAdapters(data);
      } catch (error) {
        toast(parseApiError(error));
      }
    };

    fetchEngines();
    fetchHosts();
    fetchModel();
    fetchAdapters();
  }, [params.id, toast]);

  useEffect(() => {
    if (model && engines.length > 0) {
      const filtered = engines.filter((engine) => {
        switch (model.category) {
          case "llm":
            return engine.llm_support;
          case "embedding":
            return engine.embedding_support;
          case "reranker":
            return engine.reranking_support;
          case "prompt_guard":
            return engine.prompt_guard_support;
          case "vector_db":
            return engine.vector_db_support;
          default:
            return false;
        }
      });
      setFilteredEngines(filtered);
    }
  }, [model, engines]);

  useEffect(() => {
    if (formData.engineId) {
      const selectedEngine = engines.find(
        (engine) => engine.id === formData.engineId
      );
      if (selectedEngine) {
        const defaultArgs: CLIArg[] = selectedEngine.default_args.map(
          (arg) => ({
            name: arg.name,
            value: arg.defaultValue,
            editable: arg.editable,
            new: false,
            updated: false,
          })
        );

        const defaultEnvVars: EnvVar[] = selectedEngine.default_config.map(
          (env) => ({
            name: env.name,
            value: env.defaultValue,
            editable: env.editable,
            new: false,
            updated: false,
          })
        );

        setArgs(defaultArgs);
        setEnvVars(defaultEnvVars);
      }
    }
  }, [formData.engineId, engines]);

  const handleArgChange = (
    index: number,
    field: "name" | "value",
    value: string
  ) => {
    setArgs((prev) =>
      prev.map((arg, i) =>
        i === index ? { ...arg, [field]: value, updated: true } : arg
      )
    );
  };

  const handleEnvVarChange = (
    index: number,
    field: "name" | "value",
    value: string
  ) => {
    setEnvVars((prev) =>
      prev.map((env, i) =>
        i === index ? { ...env, [field]: value, updated: true } : env
      )
    );
  };

  const addNewArgField = (e: React.MouseEvent) => {
    e.preventDefault();
    setArgs((prev) => [
      ...prev,
      { name: "", value: "", editable: true, new: true, updated: true },
    ]);
  };

  const addNewEnvVarField = (e: React.MouseEvent) => {
    e.preventDefault();
    setEnvVars((prev) => [
      ...prev,
      { name: "", value: "", editable: true, new: true, updated: true },
    ]);
  };

  const deleteArg = (index: number) => {
    setArgs((prev) => prev.filter((_, i) => i !== index));
  };

  const deleteEnvVar = (index: number) => {
    setEnvVars((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    // Validate that all argument and environment variable names are non-empty
    const invalidArgs = args.filter((arg) => arg.name.trim() === "");
    const invalidEnvVars = envVars.filter((env) => env.name.trim() === "");

    if (invalidArgs.length > 0 || invalidEnvVars.length > 0) {
      toast({
        title: "Validation Error",
        description:
          "All argument and environment variable names must be non-empty.",
        variant: "destructive",
      });
      return;
    }

    setIsSubmitting(true);
    try {
      const data = await modelService.createInferenceInstance({
        model: { id: params.id },
        engine: { id: formData.engineId },
        host: formData.hostId,
        config: {
          maxInputLength: 0,
          maxTokens: 0,
          maxBatchPrefillTokens: 0,
          maxBatchTotalTokens: 0,
          quantization: "",
          image: "",
          lora_adapters: selectedAdapters,
          args: args
            .filter((arg) => arg.new || arg.updated)
            .reduce((acc, arg) => ({ ...acc, [arg.name]: arg.value }), {}),
          env_vars: envVars
            .filter((env) => env.new || env.updated)
            .reduce((acc, env) => ({ ...acc, [env.name]: env.value }), {}),
          enable_tracing: enableTracing,
        },
      });
      toast({
        title: "Success",
        description: "Inference instance created successfully",
        variant: "success",
      });
      router.push(`/models/endpoints/${data.id}`);
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleInputChange = (
    e: React.ChangeEvent<HTMLSelectElement | HTMLInputElement>
  ) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleTabChange = (value: string) => {
    if (value !== "accelerators" && !formData.hostId) {
      toast({
        title: "Host Selection Required",
        description:
          "Please select a host from the Accelerators tab before proceeding.",
        variant: "destructive",
      });
      return;
    }
    if (value === "envVars" && !formData.engineId) {
      toast({
        title: "Engine Selection Required",
        description:
          "Please select an engine from the Deploy Config tab before proceeding.",
        variant: "destructive",
      });
      return;
    }
    setActiveTab(value);
  };

  const handleSkip = () => {
    // set host undefined and set active tab to deployConfig
    setFormData((prev) => ({ ...prev, hostId: "" }));
    setActiveTab("deployConfig");
  };

  const handleNext = () => {
    if (activeTab === "accelerators") {
      if (!formData.hostId) {
        toast({
          title: "Host Selection Required",
          description: "Please select a host or click Skip to auto-select.",
          variant: "destructive",
        });
        return;
      }
      setActiveTab("deployConfig");
    } else if (activeTab === "deployConfig") {
      if (!formData.engineId) {
        toast({
          title: "Engine Selection Required",
          description: "Please select an engine before proceeding.",
          variant: "destructive",
        });
        return;
      }
      setActiveTab("envVars");
    }
  };

  const handleAdapterChange = (adapter: Adapter, checked: boolean) => {
    setSelectedAdapters((prev) =>
      checked ? [...prev, adapter] : prev.filter((a) => a.id !== adapter.id)
    );
  };

  return (
    <form onSubmit={handleSubmit} className="max-w-6xl mx-auto">
      <Tabs value={activeTab} onValueChange={handleTabChange}>
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="accelerators">Accelerators</TabsTrigger>
          <TabsTrigger value="deployConfig" disabled={!formData.hostId}>
            Deploy Config
          </TabsTrigger>
          <TabsTrigger
            value="envVars"
            disabled={!formData.hostId || !formData.engineId}
          >
            CLI Args and Env Variables
          </TabsTrigger>
        </TabsList>
        <TabsContent value="accelerators">
          <DisplayCard
            title="Select Accelerator"
            content={
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {hosts.map((host) => (
                  <DisplayCard
                    key={host.hostname}
                    icon={<DesktopIcon className="mr-2 h-4 w-4" />}
                    className={`cursor-pointer transition duration-300 ease-in-out ${
                      formData.hostId === host.hostname
                        ? "ring-2 ring-blue-500"
                        : "hover:shadow-xl"
                    }`}
                    onClick={() =>
                      setFormData((prev) => ({
                        ...prev,
                        hostId: host.hostname,
                      }))
                    }
                    title={
                      host.gpu_model && host.gpu_model !== "N/A"
                        ? host.gpu_model
                        : host.cpu_vendor
                    }
                    content={
                      <>
                        <div className="flex flex-wrap gap-2 mb-3">
                          <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-sm">
                            Host: {host.hostname || "N/A"}
                          </span>
                        </div>
                        <div className="flex flex-wrap gap-2 mb-3">
                          {host.cpu_cores > 0 && (
                            <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded-full text-sm">
                              {host.cpu_cores} CPU Cores
                            </span>
                          )}
                          {host.cpu_cores > 0 && (
                            <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                              CPU: {host.cpu_vendor} -{" "}
                              {(host.cpu_memory / 1024).toFixed(1)} GB Memory
                            </span>
                          )}
                        </div>
                        <div className="flex flex-wrap gap-2 mb-3">
                          {host.gpu_count > 0 && (
                            <span className="px-2 py-1 bg-gray-100 text-gray-800 rounded-full text-sm">
                              {host.gpu_count} GPU
                            </span>
                          )}
                          {host.gpu_replicas > 1 && (
                            <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded-full text-sm">
                              {`${host.gpu_replicas - host.gpu_usage} / ${host.gpu_replicas} slice-free`}
                            </span>
                          )}
                          {host.gpu_memory > 0 && (
                            <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                              {(host.gpu_memory / 1024).toFixed(1)} GB GPU
                              Memory
                            </span>
                          )}
                        </div>
                      </>
                    }
                  />
                ))}
              </div>
            }
            footer={
              <div className="flex justify-between space-x-4">
                <Button
                  type="button"
                  onClick={handleSkip}
                  variant="outline"
                  icon={<ValueNoneIcon className="w-4 h-4" />}
                >
                  Skip
                </Button>
                <Button
                  type="button"
                  icon={<ThickArrowRightIcon className="w-4 h-4" />}
                  onClick={handleNext}
                >
                  Next
                </Button>
              </div>
            }
          />
        </TabsContent>
        <TabsContent value="deployConfig">
          <DisplayCard
            title="Deploy Configuration"
            content={
              <>
                <Select
                  name="engineId"
                  value={formData.engineId}
                  onValueChange={(value) =>
                    setFormData((prev) => ({ ...prev, engineId: value }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select Engine" />
                  </SelectTrigger>
                  <SelectContent>
                    {filteredEngines.map((engine) => (
                      <SelectItem key={engine.id} value={engine.id}>
                        {engine.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {formData.engineId && (
                  <div className="mt-6">
                    <div className="flex items-center space-x-2 mb-4">
                      <Switch
                        id="enable-tracing"
                        checked={enableTracing}
                        onCheckedChange={setEnableTracing}
                      />
                      <Label htmlFor="enable-tracing">Enable Tracing</Label>
                    </div>

                    {adapters.length > 0 && (
                      <>
                        <h3 className="text-lg font-semibold mb-2">
                          Select Adapters
                        </h3>
                        <div className="space-y-2">
                          {adapters.map((adapter) => (
                            <div
                              key={adapter.id}
                              className="flex items-center space-x-2"
                            >
                              <Checkbox
                                id={adapter.id}
                                checked={selectedAdapters.some(
                                  (a) => a.id === adapter.id
                                )}
                                onCheckedChange={(checked) =>
                                  handleAdapterChange(
                                    adapter,
                                    checked as boolean
                                  )
                                }
                              />
                              <Label htmlFor={adapter.id}>{adapter.name}</Label>
                            </div>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </>
            }
            footer={
              <Button type="button" onClick={handleNext}>
                <ThickArrowRightIcon className="mr-2 w-4 h-4" />
                Next
              </Button>
            }
          />
        </TabsContent>
        <TabsContent value="envVars">
          <DisplayCard
            title="CLI Args and Environment Variables"
            content={
              <>
                <h2 className="text-xl font-bold mb-4">CLI Arguments</h2>
                {args.map((arg, index) => (
                  <div key={index} className="mb-4 flex space-x-2">
                    <Input
                      value={arg.name}
                      readOnly={!arg.editable || !arg.new}
                      onChange={(e) =>
                        handleArgChange(index, "name", e.target.value)
                      }
                      placeholder="Argument Name"
                      required
                    />
                    <Input
                      value={arg.value}
                      onChange={(e) =>
                        handleArgChange(index, "value", e.target.value)
                      }
                      placeholder="Value"
                      readOnly={!arg.editable}
                    />
                    {arg.new && (
                      <Button
                        type="button"
                        variant="destructive"
                        onClick={() => deleteArg(index)}
                      >
                        Delete
                      </Button>
                    )}
                  </div>
                ))}
                <Button
                  type="button"
                  variant="outline"
                  onClick={addNewArgField}
                >
                  Add Argument
                </Button>

                <h2 className="text-xl font-bold mb-4 mt-6">
                  Environment Variables
                </h2>
                {envVars.map((env, index) => (
                  <div key={index} className="mb-4 flex space-x-2">
                    <Input
                      value={env.name}
                      readOnly={!env.editable || !env.new}
                      onChange={(e) =>
                        handleEnvVarChange(index, "name", e.target.value)
                      }
                      placeholder="Variable Name"
                      required
                    />
                    <Input
                      value={env.value}
                      onChange={(e) =>
                        handleEnvVarChange(index, "value", e.target.value)
                      }
                      placeholder="Value"
                      readOnly={!env.editable}
                    />
                    {env.new && (
                      <Button
                        type="button"
                        variant="destructive"
                        onClick={() => deleteEnvVar(index)}
                      >
                        Delete
                      </Button>
                    )}
                  </div>
                ))}
                <Button
                  type="button"
                  variant="outline"
                  onClick={addNewEnvVarField}
                >
                  Add Environment Variable
                </Button>
              </>
            }
            footer={
              <Button
                type="submit"
                icon={<RocketIcon className="mr-2 w-4 h-4" />}
                loading={isSubmitting}
              >
                {isSubmitting ? "Creating..." : "Create Inference Endpoint"}
              </Button>
            }
          />
        </TabsContent>
      </Tabs>
    </form>
  );
}
