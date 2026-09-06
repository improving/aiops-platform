interface InferenceInstance {
  id: string;
  model: Model;
  engine: Engine;
  host: string;
  endpoint: string;
  healthEndpoint: string;
  metricsEndpoint: string;
  ready: boolean;
  status: string;
  config: InferenceInstanceConfig;
  litellm_model_name?: string | null;
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
};
