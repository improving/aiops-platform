// MCP servers (backend/api/mcp.py): an organization admin registers a
// remote MCP server, and every member uses its tools in Chat, in Langflow
// and from an IDE or SDK through /v1alpha1/mcp.

export interface McpTool {
  name: string;
  description: string;
  /** The MCP readOnlyHint; null when the server sends no annotations. */
  read_only: boolean | null;
}

export type McpTransport = "http" | "sse";

/** Who can use a server: the organization, its owner alone, or every
    organization of the platform. */
export type McpScope = "organization" | "personal" | "platform";

/** When Chat asks the member before a tool of the server runs. */
export type McpApproval = "never" | "writes" | "always";

export type McpCredentialInput =
  | { auth_type: "bearer"; value: string }
  | { auth_type: "header"; auth_header: string; value: string };

export interface McpServer {
  id: string;
  name: string;
  description: string | null;
  source: string;
  url: string;
  transport: McpTransport;
  /** "none", "shared" (one credential of the organization) or
      "per_user" (each member brings their own). */
  credential_mode: "none" | "shared" | "per_user";
  /** per_user: the header a member's value goes into, and where to get
      a value. */
  credential_header: string | null;
  credential_help_url: string | null;
  /** per_user by sign-in (OAuth), not by a pasted value. */
  oauth?: boolean;
  /** The host a member signs in at (an OAuth server). */
  sign_in_host?: string | null;
  /** What the caller must do about a credential of their own:
      "not_needed" today; "set" or "missing" where a server asks each
      member for one. */
  my_credential: "not_needed" | "set" | "missing";
  /** Admins only. */
  credential_set_at: string | null;
  /** null allows every tool, new ones too. */
  allowed_tools: string[] | null;
  /** The admin's floor for approval in Chat. Absent on an older backend. */
  approval?: McpApproval;
  enabled: boolean;
  status: "connected" | "unreachable";
  checked_at: string | null;
  tools: McpTool[];
  /** A model sees each tool as `<tool_prefix><tool>`. */
  tool_prefix: string;
  /** Absent on an older backend: an organization's server. */
  scope?: McpScope;
  /** The caller may change it (an admin, its owner, a platform admin). */
  can_change?: boolean;
}

/** The tools of a server the organization allows. */
export function allowedTools(server: McpServer): McpTool[] {
  const allowed = server.allowed_tools;
  return allowed === null
    ? server.tools
    : server.tools.filter((tool) => allowed.includes(tool.name));
}

/** A server a member can turn on in Chat right now. */
export function usable(server: McpServer): boolean {
  return (
    server.enabled &&
    server.status === "connected" &&
    server.my_credential !== "missing"
  );
}
