import api from "./api";
import type { AuditFilters, AuditPage } from "@/types/organization";

const URL = "/api/v1alpha1/organizations/current/audit";

function params(filters: AuditFilters): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") out[key] = value;
  }
  return out;
}

export const auditService = {
  list: async (filters: AuditFilters) => {
    const response = await api.get<AuditPage>(URL, { params: params(filters) });
    return response.data;
  },
  /** The same rows as CSV text (backend/api/audit.py `format=csv`). */
  exportCsv: async (filters: AuditFilters) => {
    const response = await api.get<string>(URL, {
      params: { ...params(filters), format: "csv" },
      responseType: "text",
    });
    return response.data;
  },
};
