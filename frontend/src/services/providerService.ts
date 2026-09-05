import api from "./api";
import { Provider, DiscoveredModel, OrgSpend } from "@/types/models";

export const providerService = {
  getProviders: async () => {
    const response = await api.get<Provider[]>("/api/v1alpha1/providers");
    return response.data;
  },

  discoverModels: async (data: {
    kind: string;
    api_key: string;
    base_url?: string;
  }) => {
    const response = await api.post<DiscoveredModel[]>(
      "/api/v1alpha1/providers/discover",
      data
    );
    return response.data;
  },

  discoverProviderModels: async (id: string) => {
    const response = await api.post<DiscoveredModel[]>(
      `/api/v1alpha1/providers/${id}/discover`
    );
    return response.data;
  },

  createProvider: async (data: {
    kind: string;
    name: string;
    base_url?: string;
    api_key: string;
    models: string[];
    display_names?: Record<string, string>;
  }) => {
    const response = await api.post<Provider>("/api/v1alpha1/providers", data);
    return response.data;
  },

  updateProvider: async (
    id: string,
    data: {
      name?: string;
      base_url?: string;
      enabled?: boolean;
      api_key?: string;
    }
  ) => {
    const response = await api.patch<Provider>(
      `/api/v1alpha1/providers/${id}`,
      data
    );
    return response.data;
  },

  deleteProvider: async (id: string) => {
    await api.delete(`/api/v1alpha1/providers/${id}`);
  },

  addModels: async (
    id: string,
    data: { models: string[]; display_names?: Record<string, string> }
  ) => {
    const response = await api.post<Provider>(
      `/api/v1alpha1/providers/${id}/models`,
      data
    );
    return response.data;
  },

  deleteModel: async (id: string, modelId: string) => {
    await api.delete(`/api/v1alpha1/providers/${id}/models/${modelId}`);
  },

  getSpend: async () => {
    const response = await api.get<OrgSpend>(
      "/api/v1alpha1/organizations/current/spend"
    );
    return response.data;
  },

  updateBudget: async (budget_usd: number | null) => {
    const response = await api.put<OrgSpend>(
      "/api/v1alpha1/organizations/current/budget",
      { budget_usd }
    );
    return response.data;
  },
};
