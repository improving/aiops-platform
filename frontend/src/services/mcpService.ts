import api from "./api";
import type { InstanceEvent, LogsQuery, PodLogs } from "@/types/models";
import type {
  McpCatalogEntry,
  McpCatalogReview,
  McpInstance,
  McpRegistryPreview,
  McpApproval,
  McpScope,
  McpCredentialInput,
  McpServer,
  McpTool,
  McpTransport,
} from "@/types/mcp";

const SERVERS = "/api/v1alpha1/mcp/servers";
const INSTANCES = "/api/v1alpha1/mcp/instances";
const CATALOG = "/api/v1alpha1/mcp/catalog";

export interface McpServerInput {
  name: string;
  url: string;
  transport: McpTransport;
  description?: string;
  credential?: McpCredentialInput;
  allowed_tools?: string[] | null;
  approval?: McpApproval;
  scope?: McpScope;
  /** Each member signs in with OAuth; `credential` is then not used. */
  oauth?: { client_id?: string; client_secret?: string; scopes?: string[] };
  /** "per_user": `credential` is the admin's own, and every other
      member brings theirs. */
  credential_mode?: "shared" | "per_user";
  credential_help_url?: string;
}

export interface McpServerUpdate {
  description?: string;
  url?: string;
  transport?: McpTransport;
  credential?: McpCredentialInput;
  remove_credential?: boolean;
  /** Said explicitly on every credential change: on a per_user server
      the backend refuses a change that does not name the mode, because
      it deletes every member's credential. */
  credential_mode?: "none" | "shared" | "per_user";
  allowed_tools?: string[];
  allow_all_tools?: boolean;
  approval?: McpApproval;
  enabled?: boolean;
}

export const mcpService = {
  getServers: async () => (await api.get<McpServer[]>(SERVERS)).data,

  /** Connect once and list the tools; nothing is stored. */
  discover: async (data: {
    url: string;
    transport: McpTransport;
    credential?: McpCredentialInput;
  }) => (await api.post<McpTool[]>(`${SERVERS}/discover`, data)).data,

  createServer: async (data: McpServerInput) =>
    (await api.post<McpServer>(SERVERS, data)).data,

  updateServer: async (id: string, data: McpServerUpdate) =>
    (await api.patch<McpServer>(`${SERVERS}/${id}`, data)).data,

  refreshServer: async (id: string) =>
    (await api.post<McpServer>(`${SERVERS}/${id}/refresh`)).data,

  /** The caller's own credential for a per_user server; the backend
      tries it against the server before it stores it. */
  setOwnCredential: async (id: string, value: string) =>
    (await api.put<McpServer>(`${SERVERS}/${id}/credential`, { value })).data,

  // --- servers the platform deploys ---------------------------------

  getCatalog: async () => (await api.get<McpCatalogEntry[]>(CATALOG)).data,

  deploy: async (body: {
    catalog: string;
    name: string;
    description?: string;
    settings: Record<string, string>;
    approval?: McpApproval;
    /** "organization" (the default) or "platform"; never "personal". */
    scope?: McpScope;
  }) => (await api.post<McpServer>(INSTANCES, body)).data,

  getInstance: async (id: string) =>
    (await api.get<McpInstance>(`${INSTANCES}/${id}`)).data,

  /** A secret setting that is left out keeps its value. */
  updateSettings: async (id: string, settings: Record<string, string>) =>
    (await api.put<McpInstance>(`${INSTANCES}/${id}/settings`, { settings }))
      .data,

  upgradeImage: async (id: string) =>
    (await api.post<McpInstance>(`${INSTANCES}/${id}/upgrade`)).data,

  restartInstance: async (id: string) =>
    (await api.post(`${INSTANCES}/${id}/restart`)).data,

  getInstanceLogs: async (id: string, query: LogsQuery) =>
    (
      await api.get<PodLogs>(`${INSTANCES}/${id}/logs`, {
        params: {
          tail: query.tail,
          previous: query.previous,
          container: query.container,
        },
      })
    ).data,

  getInstanceEvents: async (id: string) =>
    (await api.get<InstanceEvent[]>(`${INSTANCES}/${id}/events`)).data,

  // The catalog, for a platform admin: import, review, publish.
  getCatalogEntry: async (id: string) =>
    (await api.get<McpCatalogReview>(`${CATALOG}/${id}`)).data,

  importCatalogEntry: async (name: string, slug?: string) =>
    (await api.post<McpCatalogReview>(`${CATALOG}/import`, { name, slug }))
      .data,

  updateCatalogEntry: async (
    id: string,
    changes: Partial<
      Pick<
        McpCatalogReview,
        | "name"
        | "title"
        | "description"
        | "args"
        | "port"
        | "path"
        | "egress"
        | "status"
      >
    >
  ) => (await api.patch<McpCatalogReview>(`${CATALOG}/${id}`, changes)).data,

  syncCatalogEntry: async (id: string) =>
    (await api.post<McpCatalogReview>(`${CATALOG}/${id}/sync`)).data,

  deleteCatalogEntry: async (id: string) => {
    await api.delete(`${CATALOG}/${id}`);
  },

  /** Entries of the official MCP registry (through the backend). */
  searchRegistry: async (q: string) =>
    (
      await api.get<McpRegistryPreview[]>("/api/v1alpha1/mcp/registry/search", {
        params: { q, limit: 20 },
      })
    ).data,

  /** After a refused connection test: does the server offer OAuth? */
  offersOAuth: async (url: string) => {
    try {
      return (
        await api.post<{ oauth: boolean }>(`${SERVERS}/oauth-probe`, { url })
      ).data.oauth;
    } catch {
      return false;
    }
  },

  /** Where the browser goes to sign in to an OAuth server. */
  startSignIn: async (id: string) =>
    (
      await api.post<{ authorization_url: string }>(
        `${SERVERS}/${id}/oauth/start`
      )
    ).data.authorization_url,

  /** What the authorization server sent back to the callback page. */
  finishSignIn: async (code: string, state: string, iss?: string) =>
    (
      await api.post<McpServer>("/api/v1alpha1/mcp/oauth/callback", {
        code,
        state,
        // RFC 9207: which authorization server answered, when it says so.
        ...(iss ? { iss } : {}),
      })
    ).data,

  deleteOwnCredential: async (id: string) =>
    (await api.delete<McpServer>(`${SERVERS}/${id}/credential`)).data,

  deleteServer: async (id: string) => {
    await api.delete(`${SERVERS}/${id}`);
  },
};
