import api from "./api";
import { OrgUsage } from "@/types/models";

export const usageService = {
  getUsage: async (days: number) => {
    const response = await api.get<OrgUsage>(
      "/api/v1alpha1/organizations/current/usage",
      { params: { days } }
    );
    return response.data;
  },
};
