import api from "./api";
import type {
  McpApproval,
  McpScope,
  McpCredentialInput,
  McpServer,
  McpTool,
  McpTransport,
} from "@/types/mcp";

const SERVERS = "/api/v1alpha1/mcp/servers";

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
