import api from "./api";
import {
  VectorDBSchema,
  VectorDBInstanceSchema,
  VectorDBCredentialSchema,
} from "@/types/vectordb";
import { InstanceEvent, LogsQuery, PodLogs } from "@/types/models";

export const vectorDBService = {
  getVectorDBs: async () => {
    const response = await api.get<VectorDBSchema[]>("/api/v1alpha1/vectordb");
    return response.data;
  },

  getVectorDBInstances: async () => {
    const response = await api.get<VectorDBInstanceSchema[]>(
      "/api/v1alpha1/vectordb_instances"
    );
    return response.data;
  },

  getVectorDBInstance: async (id: string) => {
    const response = await api.get<VectorDBInstanceSchema>(
      `/api/v1alpha1/vectordb_instances/${id}`
    );
    return response.data;
  },

  createVectorDBInstance: async (data: {
    vectorDB: { id: string };
    configParams: Record<string, unknown>;
  }) => {
    const response = await api.post<VectorDBInstanceSchema>(
      "/api/v1alpha1/vectordb_instances",
      data
    );
    return response.data;
  },

  deleteVectorDBInstance: async (id: string) => {
    await api.delete(`/api/v1alpha1/vectordb_instances/${id}`);
  },

  getVectorDBInstanceLogs: async (id: string, query: LogsQuery) => {
    const response = await api.get<PodLogs>(
      `/api/v1alpha1/vectordb_instances/${id}/logs`,
      { params: query }
    );
    return response.data;
  },

  getVectorDBInstanceEvents: async (id: string) => {
    const response = await api.get<InstanceEvent[]>(
      `/api/v1alpha1/vectordb_instances/${id}/events`
    );
    return response.data;
  },

  // Vector databases get restart only (spec 6.3).
  restartVectorDBInstance: async (id: string) => {
    const response = await api.post<VectorDBInstanceSchema>(
      `/api/v1alpha1/vectordb_instances/${id}/restart`
    );
    return response.data;
  },

  // Reveals the instance API key. The backend returns the value only once:
  // every later call answers with value null.
  getVectorDBCredential: async (id: string) => {
    const response = await api.get<VectorDBCredentialSchema>(
      `/api/v1alpha1/credentials/vdb/${id}`
    );
    return response.data;
  },
};
