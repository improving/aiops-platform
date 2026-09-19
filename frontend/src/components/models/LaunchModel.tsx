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
import { SettingRows } from "@/components/models/SettingRows";
import { ToolCallingSwitch } from "@/components/models/ToolCallingSwitch";
import {
  ownValues,
  rowsFromDefaults,
  type SettingRow,
} from "@/lib/instanceSettings";
import { ResourceHint } from "@/components/instances/ResourceHint";
import {
  capToContext,
  estimateGpuFit,
  freeCpu,
  freeGpu,
  freeMemory,
  oneDecimal,
} from "@/lib/launchHints";

/** True when every launchable serving option runs without a GPU. */
function cpuOnly(options: ServingOption[]): boolean {
  return options.length > 0 && options.every((option) => option.cpu);
}

// Launch resource validation (#16), mirroring
// backend/schemas/inference_instance.py's InferenceInstanceCreateSchema:
// replicas is bounded 1 to 16, and cpu/memory must be Kubernetes quantities
// ("4", "500m", "16Gi", "0.5") no longer than 32 characters.
export const REPLICAS_MIN = 1;
export const REPLICAS_MAX = 16;
export const QUANTITY_PATTERN = /^[0-9]+(\.[0-9]+)?(m|[EPTGMK]i?)?$/;
export const QUANTITY_MAX_LENGTH = 32;

export default function LaunchModel({ params }: { params: { id: string } }) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState("accelerators");
  const [formData, setFormData] = useState({
    hostId: "",
    servingOptionId: "",
  });
  const [args, setArgs] = useState<SettingRow[]>([]);
  const [envVars, setEnvVars] = useState<SettingRow[]>([]);
  const [engines, setEngines] = useState<Engine[]>([]);
  const [hosts, setHosts] = useState<Host[]>([]);
  const [model, setModel] = useState<Model | null>(null);
  const [servingOptions, setServingOptions] = useState<ServingOption[]>([]);
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [selectedAdapters, setSelectedAdapters] = useState<Adapter[]>([]);
  const { toast } = useToast(); // Initialize toast
  const [enableTracing, setEnableTracing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Launch resources (#16): sent as top-level fields of the create body.
  const [resources, setResources] = useState({
    gpuCount: 1,
    replicas: "1",
    cpu: "",
    memory: "",
  });

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

  // The hints of the form (lib/launchHints.ts): what is free on the picked
  // host and whether the weights fit its GPU. Shown inline, never as a
  // toast and never as a gate: the scheduler decides, and an instance that
  // does not fit waits as Pending with the scheduler's reason.
  const selectedHost = hosts.find((h) => h.hostname === formData.hostId);
  const selectedEngineName = engines.find(
    (e) => e.id === selectedOption?.engine_id
  )?.name;
  const replicaCount = Math.max(1, Number(resources.replicas) || 1);
  const usesGpu = Boolean(selectedOption) && !selectedOption?.cpu;
  const cpuHint = selectedHost
    ? freeCpu(selectedHost, resources.cpu, replicaCount)
    : null;
  const memoryHint = selectedHost
    ? freeMemory(selectedHost, resources.memory, replicaCount)
    : null;
  const gpuHint =
    selectedHost && usesGpu
      ? freeGpu(selectedHost, resources.gpuCount, replicaCount)
      : null;
  const gpuFit = usesGpu
    ? estimateGpuFit(model, selectedHost, resources.gpuCount)
    : null;

  // Reset the CLI args and env vars to the selected engine's defaults
  // whenever the picked serving option changes, or the engine list is
  // reloaded with a different number of entries. The key is the engine
  // list's length, not its contents, so a reload that comes back with the
  // same count does not reset the user's edits.
  // Adjusted during render, per https://react.dev/learn/you-might-not-need-an-effect,
  // rather than in an effect, because args/envVars must stay editable
  // afterwards (a plain derived value would not allow the user's edits).
  const defaultsKey = selectedOption
    ? `${selectedOption.id}:${engines.length}:${model?.context_length ?? ""}`
    : null;
  const [appliedDefaultsKey, setAppliedDefaultsKey] = useState<string | null>(
    null
  );
  if (!selectedOption && appliedDefaultsKey !== null) {
    // Guards a selectedOption transition of set -> undefined -> the same
    // value, which would otherwise skip the reset below.
    setAppliedDefaultsKey(null);
  }
  if (selectedOption && defaultsKey !== appliedDefaultsKey) {
    const selectedEngine = engines.find(
      (engine) => engine.id === selectedOption.engine_id
    );
    if (selectedEngine) {
      setAppliedDefaultsKey(defaultsKey);

      // vLLM refuses a max_model_len above the model's own context, so a
      // model with a shorter one starts from its own value; own here
      // makes rowsFromDefaults send it, since the backend merges the
      // defaults.
      const ownArgs: Record<string, string> = {};
      for (const arg of selectedEngine.default_args) {
        const value = capToContext(
          arg.name,
          arg.defaultValue,
          model?.context_length
        );
        if (value !== arg.defaultValue) ownArgs[arg.name] = value;
      }

      setArgs(rowsFromDefaults(selectedEngine.default_args, ownArgs));
      setEnvVars(rowsFromDefaults(selectedEngine.default_config));
    }
  }

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

    const replicas = Number(resources.replicas);
    if (
      !Number.isInteger(replicas) ||
      replicas < REPLICAS_MIN ||
      replicas > REPLICAS_MAX
    ) {
      toast({
        title: `Replicas must be a whole number from ${REPLICAS_MIN} to ${REPLICAS_MAX}`,
        variant: "destructive",
      });
      return;
    }

    const cpu = resources.cpu.trim();
    if (
      cpu &&
      (cpu.length > QUANTITY_MAX_LENGTH || !QUANTITY_PATTERN.test(cpu))
    ) {
      toast({
        title: "CPU must be a Kubernetes quantity such as 2 or 500m",
        variant: "destructive",
      });
      return;
    }

    const memory = resources.memory.trim();
    if (
      memory &&
      (memory.length > QUANTITY_MAX_LENGTH || !QUANTITY_PATTERN.test(memory))
    ) {
      toast({
        title: "Memory must be a Kubernetes quantity such as 8Gi",
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
        gpu_count: selectedOption?.cpu ? 1 : resources.gpuCount,
        replicas,
        cpu: cpu || undefined,
        memory: memory || undefined,
        config: {
          maxInputLength: 0,
          maxTokens: 0,
          maxBatchPrefillTokens: 0,
          maxBatchTotalTokens: 0,
          quantization: "",
          image: "",
          lora_adapters: selectedAdapters,
          args: ownValues(args),
          env_vars: ownValues(envVars),
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
                            {(host.allocatable_cpu ?? 0) > 0 && (
                              <span className="px-2 py-1 bg-yellow-100 text-yellow-800 rounded-full text-sm">
                                {oneDecimal(
                                  Math.max(
                                    0,
                                    (host.allocatable_cpu ?? 0) -
                                      (host.requested_cpu ?? 0)
                                  )
                                )}{" "}
                                of {oneDecimal(host.allocatable_cpu ?? 0)} CPU
                                free
                              </span>
                            )}
                            {(host.allocatable_memory ?? 0) > 0 && (
                              <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-sm">
                                {oneDecimal(
                                  Math.max(
                                    0,
                                    (host.allocatable_memory ?? 0) -
                                      (host.requested_memory ?? 0)
                                  ) / 1024
                                )}{" "}
                                of{" "}
                                {oneDecimal(
                                  (host.allocatable_memory ?? 0) / 1024
                                )}{" "}
                                GiB memory free
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
                            {host.gpu_count > 0 && host.gpu_replicas <= 1 && (
                              <span
                                className={`px-2 py-1 rounded-full text-sm ${
                                  host.gpu_usage >= host.gpu_count
                                    ? "bg-amber-100 text-amber-900"
                                    : "bg-green-100 text-green-800"
                                }`}
                              >
                                {host.gpu_usage >= host.gpu_count
                                  ? "GPU in use"
                                  : `${host.gpu_count - host.gpu_usage} GPU free`}
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
                  <SelectTrigger aria-label="Engine">
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
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                      {!selectedOption?.cpu && (
                        <div className="grid gap-1">
                          <Label htmlFor="gpu-count">GPU count</Label>
                          <Select
                            value={String(resources.gpuCount)}
                            onValueChange={(value) =>
                              setResources((prev) => ({
                                ...prev,
                                gpuCount: Number(value),
                              }))
                            }
                          >
                            <SelectTrigger
                              id="gpu-count"
                              aria-label="GPU count"
                            >
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {[1, 2, 4, 8].map((n) => (
                                <SelectItem key={n} value={String(n)}>
                                  {n}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <ResourceHint
                            id="gpu-hint"
                            resource={gpuHint}
                            unit={
                              (selectedHost?.gpu_replicas ?? 1) > 1
                                ? "GPU slices"
                                : "GPUs"
                            }
                            hostname={selectedHost?.hostname ?? ""}
                            overMessage="The instance waits as Pending until a GPU is free: stop another GPU instance or notebook first"
                          />
                          {gpuFit && (
                            <p
                              data-slot="gpu-fit"
                              role={
                                gpuFit.fits && !gpuFit.sliced
                                  ? "status"
                                  : "alert"
                              }
                              className={`text-xs ${
                                !gpuFit.fits || gpuFit.sliced
                                  ? "text-destructive"
                                  : gpuFit.tight
                                    ? "text-amber-700 dark:text-amber-400"
                                    : "text-muted-foreground"
                              }`}
                            >
                              {gpuFit.sliced
                                ? "This GPU is time-sliced: more than one slice adds no memory, and an engine cannot split a model across slices of one GPU. Use GPU count 1. "
                                : ""}
                              Weights about {oneDecimal(gpuFit.weightsGiB)} GiB
                              of {oneDecimal(gpuFit.gpuGiB)} GiB GPU memory.{" "}
                              {gpuFit.fits
                                ? `About ${oneDecimal(gpuFit.cacheGiB)} GiB stays for the KV cache (context and parallel requests)${
                                    gpuFit.tight
                                      ? ": little, so keep max_model_len small"
                                      : ""
                                  }.`
                                : "The weights do not fit: pick a quantized variant (AWQ, GPTQ), a smaller model, or more GPUs."}{" "}
                              An estimate: a long context needs more.
                            </p>
                          )}
                        </div>
                      )}
                      <div className="grid gap-1">
                        <Label htmlFor="replicas">Replicas</Label>
                        <Input
                          id="replicas"
                          type="text"
                          inputMode="numeric"
                          value={resources.replicas}
                          onChange={(e) =>
                            setResources((prev) => ({
                              ...prev,
                              replicas: e.target.value,
                            }))
                          }
                        />
                      </div>
                      <div className="grid gap-1">
                        <Label htmlFor="cpu">CPU</Label>
                        <Input
                          id="cpu"
                          type="text"
                          placeholder="e.g. 4"
                          value={resources.cpu}
                          aria-describedby="cpu-help"
                          onChange={(e) =>
                            setResources((prev) => ({
                              ...prev,
                              cpu: e.target.value,
                            }))
                          }
                        />
                        <p
                          id="cpu-help"
                          className="text-xs text-muted-foreground"
                        >
                          Cores for each replica, for example 4 or 500m. Empty:
                          no reservation, the pod takes what is free.
                        </p>
                        <ResourceHint
                          id="cpu-hint"
                          resource={cpuHint}
                          unit="CPU cores"
                          hostname={selectedHost?.hostname ?? ""}
                          overMessage="More than is free: the instance would wait as Pending"
                        />
                      </div>
                      <div className="grid gap-1">
                        <Label htmlFor="memory">Memory</Label>
                        <Input
                          id="memory"
                          type="text"
                          placeholder="e.g. 16Gi"
                          value={resources.memory}
                          aria-describedby="memory-help"
                          onChange={(e) =>
                            setResources((prev) => ({
                              ...prev,
                              memory: e.target.value,
                            }))
                          }
                        />
                        <p
                          id="memory-help"
                          className="text-xs text-muted-foreground"
                        >
                          Memory for each replica, for example 16Gi. Empty: no
                          reservation. A GPU engine needs little host memory;
                          the model sits in GPU memory.
                        </p>
                        <ResourceHint
                          id="memory-hint"
                          resource={memoryHint}
                          unit="GiB memory"
                          hostname={selectedHost?.hostname ?? ""}
                          overMessage="More than is free: the instance would wait as Pending"
                        />
                      </div>
                    </div>
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
                {selectedEngineName === "vLLM" && (
                  <ToolCallingSwitch
                    rows={args}
                    onChange={setArgs}
                    modelReference={
                      selectedOption?.reference ?? model?.modelId ?? ""
                    }
                  />
                )}
                <SettingRows
                  kind="arg"
                  rows={args}
                  onChange={setArgs}
                  engineName={selectedEngineName}
                />

                <h2 className="text-xl font-bold mb-4 mt-6">
                  Environment Variables
                </h2>
                <SettingRows
                  kind="env"
                  rows={envVars}
                  onChange={setEnvVars}
                  engineName={selectedEngineName}
                />
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
