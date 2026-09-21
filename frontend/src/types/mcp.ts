import type { LaunchProgress } from "@/types/models";
// MCP servers (backend/api/mcp.py): an organization admin registers a
// remote MCP server, and every member uses its tools in Chat, in Langflow
// and from an IDE or SDK through /v1alpha1/mcp.

export interface McpTool {
  name: string;
  description: string;
  /** The MCP readOnlyHint; null when the server sends no annotations. */
  read_only: boolean | null;
  /** Characters of the whole definition; absent on an older tool list. */
  size?: number | null;
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
  /** The workload of a server the platform deployed; absent for a remote one. */
  deploy?: McpDeploy | null;
}

/** The tools of a server the organization allows. */
export function allowedTools(server: McpServer): McpTool[] {
  const allowed = server.allowed_tools;
  return allowed === null
    ? server.tools
    : server.tools.filter((tool) => allowed.includes(tool.name));
}

/** A server a member can turn on in Chat right now. */
/** One entry of the official MCP registry, as the backend previews it. */
export interface McpRegistryPreview {
  name: string;
  title: string;
  description: string | null;
  version: string | null;
  publisher: string;
  website: string | null;
  /** A valid server name to start from. */
  suggested_name: string;
  remote: {
    url: string;
    transport: McpTransport;
    auth_type: "none" | "bearer" | "header";
    auth_header: string | null;
  } | null;
  remote_reason: string | null;
  deployable: boolean;
  deployable_reason: string | null;
  already_added: boolean;
  /** For a platform admin: the deploy catalog has this entry. */
  already_imported?: boolean;
}

export function usable(server: McpServer): boolean {
  return (
    server.enabled &&
    server.status === "connected" &&
    server.my_credential !== "missing" &&
    // A deployed server: its pod serves and the proxy knows it.
    (server.deploy ? server.deploy.usable : true)
  );
}

/** Who a server is for, as the add and the deploy dialog say it. */
export const SCOPE_LABEL: Record<McpScope, string> = {
  organization: "Every member of this organization",
  personal: "Only me",
  platform: "Every organization of the platform",
};

/** A deployed server that is still on its way: worth polling for. */
export function isStarting(server: McpServer): boolean {
  const deploy = server.deploy;
  return (
    !!deploy && server.enabled && !deploy.usable && deploy.status !== "Failed"
  );
}

/** The workload side of a deployed server. */
export interface McpDeploy {
  instance_id: string;
  catalog: string;
  catalog_title: string;
  image: string;
  tag: string;
  status: string | null;
  ready: boolean;
  launch: LaunchProgress | null;
  last_error: string | null;
  last_error_at: string | null;
  usable: boolean;
  upgrade_available: boolean;
}

export interface McpSetting {
  name: string;
  label: string;
  help: string;
  secret: boolean;
  required: boolean;
  /** A switch that adds this argument, not an environment variable. */
  flag: string | null;
  default: string | null;
}

export type McpEgress = "none" | "public" | "cluster";
export type McpCatalogStatus = "draft" | "published" | "deprecated";

export interface McpCatalogEntry {
  id: string;
  name: string;
  title: string;
  description: string | null;
  docs_url: string | null;
  image: string;
  tag: string;
  port: number;
  path: string;
  settings: McpSetting[];
  egress: McpEgress;
  source: string;
  source_id: string;
  source_version: string | null;
  status: McpCatalogStatus;
}

/** What a platform admin reads before Publish. */
export interface McpCatalogReview extends McpCatalogEntry {
  command: string[];
  args: string[];
  notes: string[];
  in_use: number;
}

export interface McpInstance extends McpDeploy {
  server_id: string;
  name: string;
  settings: Record<string, string>;
  secret_settings: string[];
  schema: McpSetting[];
}
