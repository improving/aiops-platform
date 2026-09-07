import api from "./api";
import type { ApiToken, CreatedApiToken } from "@/types/organization";

const URL = "/api/v1alpha1/tokens";

export const tokenService = {
  list: async (all = false) => {
    const response = await api.get<ApiToken[]>(URL, {
      params: all ? { all: "true" } : {},
    });
    return response.data;
  },
  create: async (body: {
    name: string;
    scope: "read" | "write";
    expires_in_days: number;
  }) => {
    const response = await api.post<CreatedApiToken>(URL, body);
    return response.data;
  },
  revoke: async (id: string) => {
    await api.delete(`${URL}/${id}`);
  },
};
