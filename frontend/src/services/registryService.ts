import api from "./api";
import { Model, RegistryEntryPreview } from "@/types/models";

// /v1alpha1/registry (backend/api/registry.py): the admin surface that
// feeds the members' catalog (GET /v1alpha1/models, status "published"
// only). Writes are admin-only; the backend enforces that regardless of
// what the UI shows.
export const registryService = {
  listEntries: async (params?: {
    status?: string;
    source?: string;
    capability?: string;
    q?: string;
  }) => {
    const response = await api.get<Model[]>("/api/v1alpha1/registry", {
      params,
    });
    return response.data;
  },

  // Previews for the "Import from Hugging Face"/"Add Ollama model"/"Add
  // hosted model" dialogs. Ollama has no listing endpoint: q is a full
  // name:tag reference and the answer is the one preview its manifest gives.
  search: async (source: string, q: string, limit = 20) => {
    const response = await api.get<RegistryEntryPreview[]>(
      "/api/v1alpha1/registry/search",
      { params: { source, q, limit } }
    );
    return response.data;
  },

  importEntry: async (data: {
    source: string;
    source_id: string;
    status?: string;
    // Required for source === "openrouter": an enabled OpenRouter provider
    // to register the model under, so it becomes a chat target too.
    provider_id?: string;
  }) => {
    const response = await api.post<Model>(
      "/api/v1alpha1/registry/import",
      data
    );
    return response.data;
  },

  manualCreate: async (data: {
    name: string;
    model_id: string;
    category: string;
    subcategory?: string;
    description?: string;
    size?: number;
    license?: string;
    serving_options: { engine: string; reference: string }[];
  }) => {
    const response = await api.post<Model>(
      "/api/v1alpha1/registry/manual",
      data
    );
    return response.data;
  },

  update: async (
    id: string,
    data: {
      name?: string;
      description?: string;
      license?: string;
      status?: string;
      context_length?: number;
      capabilities?: string[];
      serving_options?: { engine: string; reference: string }[];
    }
  ) => {
    const response = await api.patch<Model>(
      `/api/v1alpha1/registry/${id}`,
      data
    );
    return response.data;
  },

  sync: async (id: string) => {
    const response = await api.post<Model>(`/api/v1alpha1/registry/${id}/sync`);
    return response.data;
  },

  remove: async (id: string) => {
    await api.delete(`/api/v1alpha1/registry/${id}`);
  },
};
