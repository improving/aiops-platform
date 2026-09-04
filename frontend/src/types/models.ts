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
}

interface InferenceInstanceConfig {
  id: string;
  lora_adapters: Adapter[];
  env_vars: Record<string, string>;
  args: Record<string, string>;
  enable_tracing: boolean;
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

interface Model {
  id: string;
  name: string;
  modelId: string;
  description: string;
  category: string;
  subcategory: string;
  size: number;
  countAdapters: number;
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
  InferenceInstance,
  InferenceInstanceDashboard,
  Engine,
  Host,
  Model,
  Adapter,
  FineTuneConfig,
  FineTuneParams,
  Dataset,
  FineTuneJob,
  EngineDefaultConfigEnvVars,
  EngineDefaultConfigArgs,
};
