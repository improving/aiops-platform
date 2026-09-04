import api from "./api";
import {
  Model,
  InferenceInstance,
  InferenceInstanceDashboard,
  Adapter,
  FineTuneJob,
  Engine,
  Host,
  FineTuneConfig,
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

  importModel: async (data: {
    name: string;
    modelId: string;
    description: string;
    category: string;
    subcategory: string;
    size: number;
  }) => {
    const response = await api.post<Model>("/api/v1alpha1/models", data);
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

  getInferenceInstanceDashboards: async (id: string) => {
    const response = await api.get<InferenceInstanceDashboard[]>(
      `/api/v1alpha1/inferenceInstance/${id}/dashboards`
    );
    return response.data;
  },

  deleteInferenceInstance: async (id: string) => {
    await api.delete(`/api/v1alpha1/inferenceInstance/${id}`);
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
    const response = await api.get<string>(
      `/api/v1alpha1/models/${modelId}/finetune/${jobId}/logs`
    );
    return response.data;
  },

  deleteFineTuneJob: async (modelId: string, jobId: string) => {
    await api.delete(`/api/v1alpha1/models/${modelId}/finetune/${jobId}`);
  },

  createInferenceInstance: async (data: {
    model: { id: string };
    engine: { id: string };
    host: string;
    config: Record<string, unknown>;
  }) => {
    const response = await api.post<InferenceInstance>(
      "/api/v1alpha1/inferenceInstance",
      data
    );
    return response.data;
  },
};
