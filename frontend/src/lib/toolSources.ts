import { createMCPClient } from "@ai-sdk/mcp";
import { jsonSchema, tool, type ToolSet } from "ai";
import { backendUrl } from "@/lib/backend";

/**
 * Where the tools of one chat request come from. One kind today: MCP
 * servers of the organization, by name. The request carries a list, and
 * each kind has a resolver here, so a tool typed in the playground or a
 * built-in one is a new member of the union and a new resolver, not a
 * change to the route or to the page's request.
 */
export type McpToolSource = { type: "mcp"; server: string };

/** A function the user typed in the playground: the model may call it,
    nothing runs, and the user types the result (what a developer does
    to try a function-calling prompt before the function exists). */
export type FunctionToolSource = {
  type: "function";
  name: string;
  description: string;
  /** A JSON Schema of type "object". */
  parameters: Record<string, unknown>;
};

export type ToolSource = McpToolSource | FunctionToolSource;

/** No "-": that is what ends the server alias in an MCP tool's name, so
    a typed function can never take the name of a platform tool. */
export const FUNCTION_NAME = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;
const MAX_FUNCTIONS = 16;

/** The platform's MCP endpoint header that names the servers. */
const SERVERS_HEADER = "X-Mcp-Servers";

/** A model rarely needs more; a loop that does not end costs a CPU
    model minutes. */
export const MAX_TOOL_STEPS = 8;

/**
 * What the model is told when tools are on and the user wrote no system
 * prompt. Measured on Qwen2.5 14B AWQ (vLLM, default temperature): with
 * tool definitions and no system message the first step sometimes began
 * with text in another language plus a JSON copy of the call, or with
 * "plans" in JSON, before the real call (5 of 24 runs under load). With
 * an instruction like this one: 0 of 16. A user's own system prompt is
 * sent as it is, never with this added.
 */
export const DEFAULT_TOOL_INSTRUCTIONS =
  "You can call tools. When a tool helps, call it, and write nothing before the call: no plan, no JSON, no description of the call. After the results, answer the user directly, in the language the user wrote in.";

/**
 * How much text of ONE tool result goes back to the model (and into the
 * conversation the next request carries). A documentation tool can
 * answer with tens of thousands of characters; measured on the lab, one
 * turn with two such results took about 7,000 of a 16,384-token window.
 * About four characters make a token, so this is near 4,000 tokens. The
 * cut is said in the result itself, so the model and the reader know.
 */
export const MAX_TOOL_RESULT_CHARS = 16_000;

function truncationNote(dropped: number): string {
  return `\n\n[The platform cut this tool result: ${dropped.toLocaleString("en-US")} more characters were left out to keep the model's context window free. Ask for a narrower result if something is missing.]`;
}

/** The text parts of an MCP result, cut to the budget in order; other
    parts (images, resources) and other shapes pass as they are. */
export function capToolResult(result: unknown): unknown {
  if (!result || typeof result !== "object") return result;
  const content = (result as { content?: unknown }).content;
  if (!Array.isArray(content)) return result;
  let left = MAX_TOOL_RESULT_CHARS;
  let dropped = 0;
  const capped = content.map((part) => {
    if (
      !part ||
      typeof part !== "object" ||
      (part as { type?: unknown }).type !== "text" ||
      typeof (part as { text?: unknown }).text !== "string"
    ) {
      return part;
    }
    const text = (part as { text: string }).text;
    if (text.length <= left) {
      left -= text.length;
      return part;
    }
    dropped += text.length - left;
    const kept = text.slice(0, left);
    left = 0;
    return { ...part, text: kept };
  });
  if (dropped === 0) return result;
  return {
    ...result,
    content: [...capped, { type: "text", text: truncationNote(dropped) }],
  };
}

function withCappedResults(tools: ToolSet): ToolSet {
  return Object.fromEntries(
    Object.entries(tools).map(([name, tool]) => {
      const execute = tool.execute;
      if (!execute) return [name, tool];
      return [
        name,
        {
          ...tool,
          execute: async (...args: Parameters<typeof execute>) =>
            capToolResult(await execute(...args)),
        },
      ];
    })
  ) as ToolSet;
}

export type ResolvedTools = {
  tools: ToolSet;
  /** The admin's floor: does this tool call wait for the member's yes?
      (`McpServer.approval`: never, writes, always.) */
  needsApproval: (toolName: string) => boolean;
  /** Release what the resolvers opened; safe to call more than once. */
  close: () => Promise<void>;
};

export class ToolSourceError extends Error {}

function isMcpSource(value: unknown): value is McpToolSource {
  const v = value as McpToolSource;
  return (
    !!v &&
    typeof v === "object" &&
    v.type === "mcp" &&
    typeof v.server === "string" &&
    /^[a-z][a-z0-9_]*$/.test(v.server)
  );
}

function isFunctionSource(value: unknown): value is FunctionToolSource {
  const v = value as FunctionToolSource;
  return (
    !!v &&
    typeof v === "object" &&
    v.type === "function" &&
    typeof v.name === "string" &&
    FUNCTION_NAME.test(v.name) &&
    typeof v.description === "string" &&
    !!v.parameters &&
    typeof v.parameters === "object" &&
    !Array.isArray(v.parameters) &&
    (v.parameters as { type?: unknown }).type === "object"
  );
}

/** Only what this file knows how to resolve; the rest is dropped. */
export function parseToolSources(value: unknown): ToolSource[] {
  if (!Array.isArray(value)) return [];
  const functions = value.filter(isFunctionSource).slice(0, MAX_FUNCTIONS);
  return [...value.filter(isMcpSource), ...functions];
}

/** Tools with no executor: the loop stops at the call, and the page
    asks the user for the result. */
function resolveFunctions(sources: FunctionToolSource[]): ToolSet {
  return Object.fromEntries(
    sources.map((f) => [
      f.name,
      tool({
        description: f.description,
        inputSchema: jsonSchema(f.parameters),
      }),
    ])
  ) as ToolSet;
}

/**
 * One MCP client for all the named servers: the platform endpoint
 * (`/v1alpha1/mcp`) is one MCP server with the tools of every server it
 * is asked for. `headers` are the caller's (the session bearer, the
 * organization): the backend holds the credentials, this process none.
 */
type ServerPolicy = {
  tool_prefix: string;
  approval?: "never" | "writes" | "always";
  tools: { name: string; read_only: boolean | null }[];
};

/**
 * The approval policy of the named servers, read from the backend with
 * the caller's own headers: the route decides with what the platform
 * says, never with what the browser sent. A failure to read it asks for
 * every call (the safe side), since the tools themselves did load.
 */
async function approvalPolicy(
  servers: string[],
  headers: Record<string, string>
): Promise<(toolName: string) => boolean> {
  let listed: (ServerPolicy & { name: string })[];
  try {
    const response = await fetch(`${backendUrl()}/v1alpha1/mcp/servers`, {
      headers,
      cache: "no-store",
    });
    if (!response.ok) return () => true;
    listed = await response.json();
  } catch {
    return () => true;
  }
  const policies = listed.filter((s) => servers.includes(s.name));
  return (toolName: string) => {
    const server = policies.find((s) => toolName.startsWith(s.tool_prefix));
    // A tool of no known server: do not run it unasked.
    if (!server) return true;
    const mode = server.approval ?? "never";
    if (mode === "always") return true;
    if (mode === "never") return false;
    const tool = server.tools.find(
      (t) => `${server.tool_prefix}${t.name}` === toolName
    );
    // "writes": everything that does not say it only reads.
    return tool?.read_only !== true;
  };
}

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
    const [tools, needsApproval] = await Promise.all([
      client.tools(),
      approvalPolicy(servers, headers),
    ]);
    const opened = client;
    let closed = false;
    return {
      tools: withCappedResults(tools as ToolSet),
      needsApproval,
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
    ...new Set(
      sources
        .filter((s): s is McpToolSource => s.type === "mcp")
        .map((s) => s.server)
    ),
  ];
  const functions = resolveFunctions(
    sources.filter((s): s is FunctionToolSource => s.type === "function")
  );
  const typed = new Set(Object.keys(functions));
  if (servers.length === 0) {
    return {
      tools: functions,
      needsApproval: () => false,
      close: async () => undefined,
    };
  }
  const mcp = await resolveMcp(servers, headers);
  return {
    ...mcp,
    tools: { ...mcp.tools, ...functions },
    // A typed function runs nowhere, so there is nothing to approve.
    needsApproval: (name) => !typed.has(name) && mcp.needsApproval(name),
  };
}
