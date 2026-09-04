// Backend API base; src/proxy.ts rewrites /api/v1alpha1/* requests to it.
export const BACKEND_URL =
  process.env.NEXT_PUBLIC_AIOPS_BACKEND_URL || "http://localhost:8000";
// Optional embedded tools. An empty value renders a "not configured" card
// instead of an iframe.
export const LANGFLOW_URL = process.env.NEXT_PUBLIC_LANGFLOW_URL || "";
export const GRAFANA_URL = process.env.NEXT_PUBLIC_GRAFANA_URL || "";
export const JAEGER_URL = process.env.NEXT_PUBLIC_JAEGER_URL || "";
