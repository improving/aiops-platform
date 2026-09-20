import { allowedTools, type McpServer } from "@/types/mcp";

// A tool definition is JSON: about 3.5 characters for each token
// (measured on the lab: Linear's 66 definitions are 58,000 characters and
// fill a 16k window).
const CHARS_PER_TOKEN = 3.5;
// A tool that was listed before its size was kept: a small input schema.
const UNKNOWN_SCHEMA_CHARS = 600;
// What the platform's wrapper adds to each definition (the alias prefix,
// the JSON around it).
const OVERHEAD_CHARS = 80;
/** From this share of the window on, the Tools section warns. */
export const TOOLS_WARN_SHARE = 0.4;

export type ToolBudget = {
  tools: number;
  tokens: number;
  /** tokens / window, or null when the window is not known. */
  share: number | null;
  warn: boolean;
  /** The server that takes the most, to name in the warning. */
  largest: { name: string; tokens: number } | null;
};

function tokens(chars: number): number {
  return Math.ceil(chars / CHARS_PER_TOKEN);
}

/**
 * How much of the target's window the tool definitions take, before a
 * message is sent. The definitions go with EVERY step of a tool loop, so
 * a server with many tools can leave a small model no room for the
 * conversation (found on the lab: Linear's 66 tools, Grafana's 52).
 * An estimate: the real figure shows in the window meter after the first
 * answer.
 */
export function toolBudget(
  servers: McpServer[],
  active: string[],
  functions: { name: string; description: string; parameters: unknown }[],
  window: number | null | undefined
): ToolBudget {
  let total = 0;
  let count = 0;
  let largest: ToolBudget["largest"] = null;
  for (const server of servers) {
    if (!active.includes(server.name)) continue;
    let ofServer = 0;
    for (const tool of allowedTools(server)) {
      const size =
        tool.size ??
        tool.name.length + tool.description.length + UNKNOWN_SCHEMA_CHARS;
      ofServer += tokens(size + OVERHEAD_CHARS);
      count += 1;
    }
    total += ofServer;
    if (!largest || ofServer > largest.tokens)
      largest = { name: server.name, tokens: ofServer };
  }
  for (const fn of functions) {
    total += tokens(
      fn.name.length +
        fn.description.length +
        (typeof fn.parameters === "string"
          ? fn.parameters.length
          : JSON.stringify(fn.parameters ?? {}).length) +
        OVERHEAD_CHARS
    );
    count += 1;
  }
  const share = window && window > 0 ? total / window : null;
  return {
    tools: count,
    tokens: total,
    share,
    warn: share !== null && share >= TOOLS_WARN_SHARE,
    largest,
  };
}
