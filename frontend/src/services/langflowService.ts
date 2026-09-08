import api from "./api";
import { LangflowProvision } from "@/types/models";

export const langflowService = {
  /** Idempotent: writes the caller's Langflow provider variables for the
      active organization and reports what Langflow now lists. */
  provision: async () => {
    const response = await api.post<LangflowProvision>(
      "/api/v1alpha1/langflow/provision"
    );
    return response.data;
  },
};
