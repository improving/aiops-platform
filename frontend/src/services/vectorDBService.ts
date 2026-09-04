import api from "./api";
import { VectorDBSchema, VectorDBInstanceSchema } from "@/types/vectordb";

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
};
