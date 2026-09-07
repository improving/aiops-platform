import api from "./api";
import { Notebook } from "@/types/notebook";
import { InstanceEvent, LogsQuery, PodLogs } from "@/types/models";

export const notebookService = {
  createNotebook: async (data: unknown) => {
    const response = await api.post<Notebook>("/api/v1alpha1/notebooks", data);
    return response.data;
  },

  getNotebooks: async () => {
    const response = await api.get<Notebook[]>("/api/v1alpha1/notebooks");
    return response.data;
  },

  getNotebookById: async (id: string) => {
    const response = await api.get<Notebook>(`/api/v1alpha1/notebooks/${id}`);
    return response.data;
  },

  deleteNotebook: async (id: string) => {
    await api.delete(`/api/v1alpha1/notebooks/${id}`);
  },

  getNotebookLogs: async (id: string, query: LogsQuery) => {
    const response = await api.get<PodLogs>(
      `/api/v1alpha1/notebooks/${id}/logs`,
      { params: query }
    );
    return response.data;
  },

  getNotebookEvents: async (id: string) => {
    const response = await api.get<InstanceEvent[]>(
      `/api/v1alpha1/notebooks/${id}/events`
    );
    return response.data;
  },
};
