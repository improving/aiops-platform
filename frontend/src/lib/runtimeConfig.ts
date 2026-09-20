"use client";

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  AUTH_DISABLED,
  GRAFANA_URL,
  JAEGER_URL,
  LANGFLOW_URL,
} from "@/constants";

// NEXT_PUBLIC_* values are inlined at build time, so a container cannot
// change them. The backend serves the same URLs from its environment
// (GET /v1alpha1/config/ui, backend/api/config.py); this context fetches
// them once at load and falls back to the build-time values for every
// field the endpoint leaves empty or when it cannot be reached.

export type AuthMode = "oidc" | "disabled";

export type RuntimeConfig = {
  grafanaUrl: string;
  langflowUrl: string;
  jaegerUrl: string;
  authMode: AuthMode;
  /** Import from the MCP registry is on; false until the backend says so. */
  mcpRegistry: boolean;
  /** False until the endpoint answered (or failed); consumers wait for it. */
  loaded: boolean;
};

export const CONFIG_PATH = "/api/v1alpha1/config/ui";

export const BUILD_TIME_CONFIG: RuntimeConfig = {
  grafanaUrl: GRAFANA_URL,
  langflowUrl: LANGFLOW_URL,
  jaegerUrl: JAEGER_URL,
  authMode: AUTH_DISABLED ? "disabled" : "oidc",
  mcpRegistry: false,
  loaded: false,
};

type UIConfigResponse = Partial<
  Record<
    "grafanaUrl" | "langflowUrl" | "jaegerUrl" | "authMode" | "mcpRegistry",
    unknown
  >
>;

function text(value: unknown): string {
  return typeof value === "string" ? value.trim().replace(/\/+$/, "") : "";
}

/** The effective config: the response wins field by field, the build fills the gaps. */
export function mergeRuntimeConfig(
  response: UIConfigResponse | null
): RuntimeConfig {
  const authMode = response?.authMode;
  return {
    grafanaUrl: text(response?.grafanaUrl) || BUILD_TIME_CONFIG.grafanaUrl,
    langflowUrl: text(response?.langflowUrl) || BUILD_TIME_CONFIG.langflowUrl,
    jaegerUrl: text(response?.jaegerUrl) || BUILD_TIME_CONFIG.jaegerUrl,
    authMode:
      authMode === "oidc" || authMode === "disabled"
        ? authMode
        : BUILD_TIME_CONFIG.authMode,
    mcpRegistry: response?.mcpRegistry === true,
    loaded: true,
  };
}

export async function fetchRuntimeConfig(
  fetcher: typeof fetch = fetch
): Promise<RuntimeConfig> {
  try {
    const response = await fetcher(CONFIG_PATH, { cache: "no-store" });
    if (!response.ok) return mergeRuntimeConfig(null);
    return mergeRuntimeConfig((await response.json()) as UIConfigResponse);
  } catch {
    return mergeRuntimeConfig(null);
  }
}

const RuntimeConfigContext = createContext<RuntimeConfig>(BUILD_TIME_CONFIG);

export function RuntimeConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<RuntimeConfig>(BUILD_TIME_CONFIG);

  const loadConfig = useCallback(async () => {
    const next = await fetchRuntimeConfig();
    setConfig(next);
  }, []);

  useEffect(() => {
    (async () => {
      await loadConfig();
    })();
  }, [loadConfig]);

  return createElement(
    RuntimeConfigContext.Provider,
    { value: config },
    children
  );
}

export function useRuntimeConfig(): RuntimeConfig {
  return useContext(RuntimeConfigContext);
}
