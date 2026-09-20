// What an instance that is not ready yet is waiting for
// (backend/utils/kubernetes_utils.py LaunchProgress): derived from the pods
// on every read, null once the instance is ready, stopped or failed.
type LaunchPhase =
  | "Scheduling"
  | "Blocked"
  | "Pulling image"
  | "Restarting"
  | "Starting"
  | "Terminating";

interface LaunchProgress {
  phase: LaunchPhase;
  message: string;
  since?: string | null;
  // Only a person can move it on (a pod no node can take, a container that
  // cannot be created, a restart loop): the backend decides, the UI styles.
  needs_attention: boolean;
  restart_count: number;
  replicas_total: number;
  // Of the model download, while the phase is Starting and the backend can
  // see the model cache; equal once the download is complete.
  downloaded_bytes?: number | null;
  total_bytes?: number | null;
}

interface InferenceInstance {
  id: string;
  model: Model;
  engine: Engine;
  host: string;
  endpoint: string;
  healthEndpoint: string;
  metricsEndpoint: string;
  ready: boolean;
  // Set by the platform (backend/utils/instance_status.py): Pending,
  // Running, Failed or Stopped; null for a row it has not looked at yet.
  status: string | null;
  last_error?: string | null;
  last_error_at?: string | null;
  stopped_at?: string | null;
  launch?: LaunchProgress | null;
  // Launch resources (#16).
  replicas?: number;
  gpu_count?: number;
  cpu?: string | null;
  memory?: string | null;
  config: InferenceInstanceConfig;
  /** Which of its own settings the engine's controller renders: what the
      Edit settings dialog shows. Set by the backend, never guessed here. */
  settingsRead?: ("args" | "env_vars")[];
  litellm_model_name?: string | null;
  reference?: string | null;
}

// GET /v1alpha1/<kind>/{id}/logs (backend/utils/pod_inspection.py
// pod_logs): every container of every pod behind the instance.
interface PodLogs {
  pods: { name: string; containers: { name: string; log: string }[] }[];
}

// GET /v1alpha1/<kind>/{id}/events (pod_events): newest first, at most 100.
interface InstanceEvent {
  // The last time; Kubernetes folds a repeated event into one with a count.
  at: string | null;
  count?: number;
  first_at?: string | null;
  type: string;
  reason: string;
  message: string;
  object: string;
}

// The query string of a logs call; tail is 1..5000.
interface LogsQuery {
  container?: string;
  tail: number;
  previous: boolean;
}

// GET /v1alpha1/chat/targets: what the caller may chat, embed or rerank
// against (backend/api/chat.py list_targets).
interface ChatTarget {
  name: string;
  label: string;
  capability: "chat" | "embedding" | "rerank";
  instance_id: string | null;
  provider_id: string | null;
  model: string;
  engine: string;
  ready: boolean;
  via: "litellm" | "direct" | "mock";
  /** The window the target serves, in tokens; absent or null when the
      platform does not know it (every engine but vLLM, some hosted models). */
  context_length?: number | null;
  /** Whether the target answers a request that carries tools: false for
      a vLLM instance without the tool-calling flag (it answers 400) or a
      hosted model the price catalog says cannot; absent or null when
      the platform does not know (Ollama: it depends on the model). */
  tools?: boolean | null;
}

// Hosted providers (Phase 2b, backend/api/providers.py): an organization
// admin adds a provider with an API key and exposes some of its models.
interface ProviderModel {
  id: string;
  model: string;
  display_name: string;
  litellm_model_name: string;
  capability: "chat" | "embedding";
  context_length: number | null;
  input_cost_per_token: number | null;
  output_cost_per_token: number | null;
  enabled: boolean;
}

interface Provider {
  id: string;
  kind: string;
  name: string;
  base_url: string | null;
  enabled: boolean;
  // The key is never echoed back, only whether one is on file.
  has_key: boolean;
  models: ProviderModel[];
}

// POST /v1alpha1/providers/discover and /providers/{id}/discover: a
// provider's models, enriched with price fields from the local catalog.
interface DiscoveredModel {
  id: string;
  display_name: string;
  context_length: number | null;
  capability: string;
  input_cost_per_token: number | null;
  output_cost_per_token: number | null;
}

// GET/PUT /v1alpha1/organizations/current/{spend,budget}.
interface OrgSpend {
  team_id: string | null;
  spend: number;
  max_budget: number | null;
  budget_reset_at: string | null;
  budget_usd: number | null;
}

// GET /v1alpha1/organizations/current/usage: LiteLLM spend logs aggregated
// per target and per (user, target, day) (backend/api/organizations.py
// current_org_usage). `user` is null for an admin-visible unattributed row.
interface UsageTotals {
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  spend: number;
}

interface UsageByTarget extends UsageTotals {
  model: string;
  target: string;
  label: string;
}

interface UsageRow extends UsageByTarget {
  user: string | null;
  day: string;
}

interface OrgUsage {
  days: number;
  since: string;
  until: string;
  scope: "user" | "organization";
  capped: boolean;
  totals: UsageTotals;
  by_target: UsageByTarget[];
  /** MCP tool calls, most used first. Not model requests: they are not
      in `totals`. Absent on a backend before tools. */
  tools?: { server: string; tool: string; calls: number }[];
  rows: UsageRow[];
}

interface InferenceInstanceConfig {
  id: string;
  lora_adapters: Adapter[];
  env_vars: Record<string, string>;
  args: Record<string, string>;
  enable_tracing: boolean;
}

interface Credential {
  key: string;
  // Only present on the first read, or on an admin's ?reveal=true.
  value: string | null;
  shown_at: string | null;
}

interface InferenceInstanceDashboard {
  id: string;
  dashboard_id: string | null;
  dashboard_name: string | null;
  panel_id: string | null;
  panel_name: string | null;
  org_id: string;
  query_params: {
    [key: string]: string;
  };
}

interface EngineDefaultConfigArgs {
  name: string;
  chart_type: string;
  defaultValue: string;
  editable: boolean;
}

interface EngineDefaultConfigEnvVars {
  name: string;
  chart_type: string;
  defaultValue: string;
  editable: boolean;
}

interface Engine {
  id: string;
  name: string;
  llm_support: boolean;
  embedding_support: boolean;
  reranking_support: boolean;
  prompt_guard_support: boolean;
  vector_db_support: boolean;
  cpu: boolean;
  default_config: EngineDefaultConfigEnvVars[];
  default_args: EngineDefaultConfigArgs[];
}

interface Host {
  hostname: string;
  cpu_vendor: string;
  cpu_memory: number;
  cpu_cores: number;
  cuda_driver_version: string;
  cuda_runtime_version: string;
  gpu_count: number;
  gpu_memory: number;
  gpu_model: string;
  gpu_replicas: number;
  gpu_sharing_strategy: string;
  gpu_usage: number;
  // What the node offers to pods and what the pods on it already ask
  // for (backend/api/hosts.py): CPU in cores, memory in MiB. Optional, so
  // an older backend still types.
  allocatable_cpu?: number;
  allocatable_memory?: number;
  allocatable_gpu?: number;
  requested_cpu?: number;
  requested_memory?: number;
}

// One row of GET /v1alpha1/models/{id}/serving-options
// (backend/schemas/serving_option.py): which engine can run a catalog
// entry and the reference its controller needs. `engine_id` is null for a
// hosted option (e.g. "openrouter"), which has no engines row and no
// chart to launch; the launch wizard renders only options with one.
interface ServingOption {
  id: string;
  engine: string;
  reference: string;
  default_args: Record<string, string> | null;
  engine_id: string | null;
  cpu: boolean | null;
}

// GET /v1alpha1/registry/search: one registry.entry.RegistryEntry from a
// source, before it becomes a row (backend/schemas/registry.py).
interface RegistryEntryPreview {
  source: string;
  source_id: string;
  name: string;
  description: string | null;
  category: string | null;
  subcategory: string | null;
  size: number | null;
  license: string | null;
  parameters: number | null;
  context_length: number | null;
  capabilities: string[];
  formats: string[];
  tags: string[];
  serving_options: {
    engine: string;
    reference: string;
    default_args: Record<string, string> | null;
  }[];
  already_imported: boolean;
}

interface Model {
  id: string;
  name: string;
  modelId: string;
  description: string;
  category: string;
  subcategory: string;
  size: number;
  countAdapters: number;

  // Registry fields (Phase 3, backend/schemas/model.py), all additive and
  // optional: a plain launch-wizard/fine-tune caller keeps working without
  // them, and the base_model references on Adapter/FineTuneJob never carry
  // the full row.
  source?: string;
  source_id?: string | null;
  license?: string | null;
  parameters?: number | null;
  context_length?: number | null;
  capabilities?: string[];
  formats?: string[];
  tags?: string[];
  status?: string;
  synced_at?: string | null;
  sync_error?: string | null;
  serving_options?: ServingOption[] | null;
}
interface Adapter {
  id: string;
  name: string;
  hf_id: string;
  path?: string;
  base_model: Model;
}

interface Dataset {
  path: string;
  train_split: "train";
  valid_split: null;
  chat_template: "tokenizer" | "chatml" | "zephyr" | null;
  column_mapping: {
    text_column: string | null;
    prompt_text_column: string | null;
    rejected_text_column: string | null;
  };
}

interface FineTuneParams {
  unsloth: boolean; // default false
  block_size: number;
  model_max_length: number;
  epochs: number;
  batch_size: number;
  lr: number; // default 1e-5

  // peft params
  quantization: "int4" | "int8" | null;
  target_modules: "all-linear" | null;
  merge_adapter: false;
  peft: true;
  lora_r: number; // default 16
  lora_alpha: number; // default 32
  lora_dropout: number; // default 0.05

  padding: "left" | "right" | null; // default right
  optimizer: "adamw_torch" | "paged_adamw_8bit" | null; // default paged_adamw_8bit
  scheduler: "cosine" | "linear" | null; // default cosine
  gradient_accumulation: number; // default 4
  mixed_precision: "fp16" | "bf16" | null;
}

interface FineTuneConfig {
  task: string;
  base_model: string;
  project_name: string;
  log: "tensorboard";
  backend: "local";
  data: Dataset;
  params: FineTuneParams;
}

interface FineTuneJob {
  name: string;
  params: Record<string, unknown>;
  id: string;
  base_model: Model;
  status: string;
  created_at: string;
  updated_at: string;
}

export type {
  Credential,
  ChatTarget,
  Provider,
  ProviderModel,
  DiscoveredModel,
  OrgSpend,
  OrgUsage,
  UsageTotals,
  UsageByTarget,
  UsageRow,
  InferenceInstance,
  LaunchProgress,
  InferenceInstanceDashboard,
  Engine,
  Host,
  Model,
  ServingOption,
  RegistryEntryPreview,
  Adapter,
  FineTuneConfig,
  FineTuneParams,
  Dataset,
  FineTuneJob,
  EngineDefaultConfigEnvVars,
  EngineDefaultConfigArgs,
  PodLogs,
  InstanceEvent,
  LogsQuery,
};

export interface LangflowModel {
  name: string;
  label: string;
}

/** What POST /v1alpha1/langflow/provision wrote for the caller. */
export interface LangflowProvision {
  langflow_user: string;
  organization: string;
  models: LangflowModel[];
}
