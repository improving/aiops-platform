import { createMCPClient } from "@ai-sdk/mcp";
import type { ToolSet } from "ai";
import { backendUrl } from "@/lib/backend";

/**
 * Where the tools of one chat request come from. One kind today: MCP
 * servers of the organization, by name. The request carries a list, and
 * each kind has a resolver here, so a tool typed in the playground or a
 * built-in one is a new member of the union and a new resolver, not a
 * change to the route or to the page's request.
 */
export type ToolSource = { type: "mcp"; server: string };

/** The platform's MCP endpoint header that names the servers. */
const SERVERS_HEADER = "X-Mcp-Servers";

/** A model rarely needs more; a loop that does not end costs a CPU
    model minutes. */
export const MAX_TOOL_STEPS = 8;

export type ResolvedTools = {
  tools: ToolSet;
  /** Release what the resolvers opened; safe to call more than once. */
  close: () => Promise<void>;
};

export class ToolSourceError extends Error {}

function isToolSource(value: unknown): value is ToolSource {
  return (
    !!value &&
    typeof value === "object" &&
    (value as ToolSource).type === "mcp" &&
    typeof (value as ToolSource).server === "string" &&
    /^[a-z][a-z0-9_]*$/.test((value as ToolSource).server)
  );
}

/** Only what this file knows how to resolve; the rest is dropped. */
export function parseToolSources(value: unknown): ToolSource[] {
  return Array.isArray(value) ? value.filter(isToolSource) : [];
}

/**
 * One MCP client for all the named servers: the platform endpoint
 * (`/v1alpha1/mcp`) is one MCP server with the tools of every server it
 * is asked for. `headers` are the caller's (the session bearer, the
 * organization): the backend holds the credentials, this process none.
 */
async function resolveMcp(
  servers: string[],
  headers: Record<string, string>
): Promise<ResolvedTools> {
  let client;
  try {
    client = await createMCPClient({
      transport: {
        type: "http",
        url: `${backendUrl()}/v1alpha1/mcp`,
        headers: { ...headers, [SERVERS_HEADER]: servers.join(",") },
      },
    });
    const tools = await client.tools();
    const opened = client;
    let closed = false;
    return {
      tools: tools as ToolSet,
      close: async () => {
        if (closed) return;
        closed = true;
        await opened.close().catch(() => undefined);
      },
    };
  } catch (error) {
    await client?.close().catch(() => undefined);
    const reason = error instanceof Error ? error.message : String(error);
    // Said plainly, and never a silent answer without the tools the
    // user turned on.
    throw new ToolSourceError(`Could not reach the tools: ${reason}`);
  }
}

export async function resolveToolSources(
  sources: ToolSource[],
  headers: Record<string, string>
): Promise<ResolvedTools> {
  const servers = [
    ...new Set(sources.filter((s) => s.type === "mcp").map((s) => s.server)),
  ];
  if (servers.length === 0) {
    return { tools: {}, close: async () => undefined };
  }
  return resolveMcp(servers, headers);
}
