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
      tools: withCappedResults(tools as ToolSet),
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
