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

interface Engine {
  id: string;
  name: string;
  llm_support: boolean;
  embedding_support: boolean;
  reranking_support: boolean;
  prompt_guard_support: boolean;
  vector_db_support: boolean;
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
}

interface Model {
  id: string;
  name: string;
  modelId: string;
  description: string;
  category: string;
  subcategory: string;
  size: number;
}

// interface Model {
//   id: string;
//   name: string;
//   category: "llm" | "embedding" | "reranker" | "prompt_guard" | "vector_db";
// }

export type {
  InferenceInstance,
  InferenceInstanceDashboard,
  Engine,
  Host,
  Model,
};

export interface Adapter {
  id: string;
  name: string;
  hf_id: string;
  path?: string;
  base_model: Model;
}
