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
import { Adapter, Engine, Host, Model, ServingOption } from "@/types/models";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { modelService } from "@/services/modelService";
import { parseApiError } from "@/lib/utils";
import { DisplayCard } from "@/components/ui/DisplayCard";

/** True when every launchable serving option runs without a GPU. */
function cpuOnly(options: ServingOption[]): boolean {
  return options.length > 0 && options.every((option) => option.cpu);
}

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
    servingOptionId: "",
  });
  const [args, setArgs] = useState<CLIArg[]>([]);
  const [envVars, setEnvVars] = useState<EnvVar[]>([]);
  const [engines, setEngines] = useState<Engine[]>([]);
  const [hosts, setHosts] = useState<Host[]>([]);
  const [model, setModel] = useState<Model | null>(null);
  const [servingOptions, setServingOptions] = useState<ServingOption[]>([]);
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
    const fetchServingOptions = async () => {
      try {
        const data = await modelService.getModelServingOptions(params.id);
        // The wizard renders only options with an engine_id: a hosted
        // option (e.g. "openrouter") has none and no chart to launch.
        setServingOptions(data.filter((option) => option.engine_id));
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
    fetchServingOptions();
    fetchAdapters();
  }, [params.id, toast]);

  const needsHost = !cpuOnly(servingOptions);

  const selectedOption = servingOptions.find(
    (option) => option.id === formData.servingOptionId
  );

  // Reset the CLI args and env vars to the selected engine's defaults
  // whenever the picked serving option (or the loaded engines) change.
  // Adjusted during render, per https://react.dev/learn/you-might-not-need-an-effect,
  // rather than in an effect, because args/envVars must stay editable
  // afterwards (a plain derived value would not allow the user's edits).
  const defaultsKey = selectedOption
    ? `${selectedOption.id}:${engines.length}`
    : null;
  const [appliedDefaultsKey, setAppliedDefaultsKey] = useState<string | null>(
    null
  );
  if (selectedOption && defaultsKey !== appliedDefaultsKey) {
    const selectedEngine = engines.find(
      (engine) => engine.id === selectedOption.engine_id
    );
    if (selectedEngine) {
      setAppliedDefaultsKey(defaultsKey);

      const defaultArgs: CLIArg[] = selectedEngine.default_args.map((arg) => ({
        name: arg.name,
        value: arg.defaultValue,
        editable: arg.editable,
        new: false,
        updated: false,
      }));

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
        engine: { id: selectedOption?.engine_id ?? "" },
        host: formData.hostId,
        serving_option_id: formData.servingOptionId || undefined,
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

  const handleTabChange = (value: string) => {
    if (value !== "accelerators" && !formData.hostId && needsHost) {
      toast({
        title: "Host Selection Required",
        description:
          "Please select a host from the Accelerators tab before proceeding.",
        variant: "destructive",
      });
      return;
    }
    if (value === "envVars" && !formData.servingOptionId) {
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
      if (!formData.hostId && needsHost) {
        toast({
          title: "Host Selection Required",
          description: "Please select a host or click Skip to auto-select.",
          variant: "destructive",
        });
        return;
      }
      setActiveTab("deployConfig");
    } else if (activeTab === "deployConfig") {
      if (!formData.servingOptionId) {
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
          <TabsTrigger
            value="deployConfig"
            disabled={!formData.hostId && needsHost}
          >
            Deploy Config
          </TabsTrigger>
          <TabsTrigger
            value="envVars"
            disabled={
              (!formData.hostId && needsHost) || !formData.servingOptionId
            }
          >
            CLI Args and Env Variables
          </TabsTrigger>
        </TabsList>
        <TabsContent value="accelerators">
          <DisplayCard
            title={
              model
                ? `Select Accelerator — ${model.name}`
                : "Select Accelerator"
            }
            content={
              <>
                {!needsHost && (
                  <p className="mb-4 text-sm text-muted-foreground">
                    This model runs on CPU. Pick a host to pin it to a node, or
                    click Next to let the scheduler choose.
                  </p>
                )}
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
                          : "No GPU detected"
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
              </>
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
                  name="servingOptionId"
                  value={formData.servingOptionId}
                  onValueChange={(value) =>
                    setFormData((prev) => ({
                      ...prev,
                      servingOptionId: value,
                    }))
                  }
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select Engine" />
                  </SelectTrigger>
                  <SelectContent>
                    {servingOptions.map((option) => (
                      <SelectItem key={option.id} value={option.id}>
                        {option.engine}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {formData.servingOptionId && (
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
                {isSubmitting ? "Creating..." : "Create instance"}
              </Button>
            }
          />
        </TabsContent>
      </Tabs>
    </form>
  );
}
