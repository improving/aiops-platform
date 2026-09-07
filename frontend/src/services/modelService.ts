import api from "./api";
import {
  Model,
  InferenceInstance,
  InferenceInstanceDashboard,
  Adapter,
  ChatTarget,
  Credential,
  FineTuneJob,
  Engine,
  Host,
  FineTuneConfig,
  ServingOption,
  InstanceEvent,
  LogsQuery,
  PodLogs,
} from "@/types/models";

export const modelService = {
  getEngines: async () => {
    const response = await api.get<Engine[]>("/api/v1alpha1/engines");
    return response.data;
  },

  getHosts: async () => {
    const response = await api.get<Host[]>("/api/v1alpha1/hosts");
    return response.data;
  },

  getModels: async () => {
    const response = await api.get<Model[]>("/api/v1alpha1/models");
    return response.data;
  },

  getModelById: async (id: string) => {
    const response = await api.get<Model>(`/api/v1alpha1/models/${id}`);
    return response.data;
  },

  // Left-joined with the engine rows: an option whose engine has no
  // engines row (a hosted option such as "openrouter") comes back with
  // engine_id: null; the launch wizard renders only options with one.
  getModelServingOptions: async (id: string) => {
    const response = await api.get<ServingOption[]>(
      `/api/v1alpha1/models/${id}/serving-options`
    );
    return response.data;
  },

  startFineTuning: async (
    modelId: string,
    data: {
      name: string;
      params: FineTuneConfig;
    }
  ) => {
    const response = await api.post(
      `/api/v1alpha1/models/${modelId}/finetune`,
      data
    );
    return response.data;
  },

  getInferenceInstance: async (id: string) => {
    const response = await api.get<InferenceInstance>(
      `/api/v1alpha1/inferenceInstance/${id}`
    );
    return response.data;
  },

  getInferenceInstances: async () => {
    const response = await api.get<InferenceInstance[]>(
      "/api/v1alpha1/inferenceInstance"
    );
    return response.data;
  },

  getChatTargets: async () => {
    const response = await api.get<ChatTarget[]>("/api/v1alpha1/chat/targets");
    return response.data;
  },

  getInferenceInstanceDashboards: async (id: string) => {
    const response = await api.get<InferenceInstanceDashboard[]>(
      `/api/v1alpha1/inferenceInstance/${id}/dashboards`
    );
    return response.data;
  },

  deleteInferenceInstance: async (id: string) => {
    await api.delete(`/api/v1alpha1/inferenceInstance/${id}`);
  },

  // Logs and events of the instance's pods (backend/api/inference_instance.py).
  getInferenceInstanceLogs: async (id: string, query: LogsQuery) => {
    const response = await api.get<PodLogs>(
      `/api/v1alpha1/inferenceInstance/${id}/logs`,
      { params: query }
    );
    return response.data;
  },

  getInferenceInstanceEvents: async (id: string) => {
    const response = await api.get<InstanceEvent[]>(
      `/api/v1alpha1/inferenceInstance/${id}/events`
    );
    return response.data;
  },

  // Day-2 actions (#16); each answers the updated instance.
  restartInferenceInstance: async (id: string) => {
    const response = await api.post<InferenceInstance>(
      `/api/v1alpha1/inferenceInstance/${id}/restart`
    );
    return response.data;
  },

  stopInferenceInstance: async (id: string) => {
    const response = await api.post<InferenceInstance>(
      `/api/v1alpha1/inferenceInstance/${id}/stop`
    );
    return response.data;
  },

  resumeInferenceInstance: async (id: string) => {
    const response = await api.post<InferenceInstance>(
      `/api/v1alpha1/inferenceInstance/${id}/resume`
    );
    return response.data;
  },

  scaleInferenceInstance: async (id: string, replicas: number) => {
    const response = await api.post<InferenceInstance>(
      `/api/v1alpha1/inferenceInstance/${id}/scale`,
      { replicas }
    );
    return response.data;
  },

  // The value comes back once; afterwards it is null unless an admin
  // passes reveal=true (backend/api/credentials.py).
  getInferenceInstanceCredential: async (id: string, reveal = false) => {
    const response = await api.get<Credential>(
      `/api/v1alpha1/credentials/inf/${id}`,
      reveal ? { params: { reveal: true } } : undefined
    );
    return response.data;
  },

  getAdapters: async (modelId: string) => {
    const response = await api.get<Adapter[]>(
      `/api/v1alpha1/model/${modelId}/adapters`
    );
    return response.data;
  },

  createAdapter: async (
    modelId: string,
    data: {
      name: string;
      path: string;
      hf_id: string;
    }
  ) => {
    const response = await api.post(
      `/api/v1alpha1/model/${modelId}/adapters`,
      data
    );
    return response.data;
  },

  updateAdapter: async (
    modelId: string,
    adapterId: string,
    data: {
      name: string;
      path: string;
      hf_id: string;
    }
  ) => {
    const response = await api.put(
      `/api/v1alpha1/model/${modelId}/adapters/${adapterId}`,
      data
    );
    return response.data;
  },

  deleteAdapter: async (modelId: string, adapterId: string) => {
    await api.delete(`/api/v1alpha1/model/${modelId}/adapters/${adapterId}`);
  },

  getFineTuneJobs: async (modelId: string) => {
    const response = await api.get<FineTuneJob[]>(
      `/api/v1alpha1/models/${modelId}/finetune`
    );
    return response.data;
  },

  getFineTuneJobLogs: async (modelId: string, jobId: string) => {
    const response = await api.get<{ logs: string }>(
      `/api/v1alpha1/models/${modelId}/finetune/${jobId}/logs`
    );
    return response.data.logs;
  },

  deleteFineTuneJob: async (modelId: string, jobId: string) => {
    await api.delete(`/api/v1alpha1/models/${modelId}/finetune/${jobId}`);
  },

  createInferenceInstance: async (data: {
    model: { id: string };
    engine: { id: string };
    host: string;
    config: Record<string, unknown>;
    // The picked serving option (Phase 3): its reference is persisted on
    // the instance row and every consumer reads
    // instance.reference or instance.model.modelId.
    serving_option_id?: string;
    // Launch resources (#16); the backend defaults are 1, 1, null, null.
    gpu_count?: number;
    replicas?: number;
    cpu?: string;
    memory?: string;
  }) => {
    const response = await api.post<InferenceInstance>(
      "/api/v1alpha1/inferenceInstance",
      data
    );
    return response.data;
  },
};

// The picked serving option's reference is what upstream API calls (curl,
// Python snippets) must send as `model`; instances launched before Phase 3
// have no reference, so fall back to the catalog model id.
export const upstreamModel = (i: InferenceInstance) =>
  i.reference ?? i.model.modelId;
