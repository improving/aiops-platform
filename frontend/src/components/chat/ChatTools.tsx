import Link from "next/link";
import { Switch } from "@/components/ui/switch";
import { allowedTools, usable, type McpServer } from "@/types/mcp";
import type { ToolBudget } from "@/lib/toolBudget";

/** Why the tools cannot be used with this target, or "" when they can.
    `null` (unknown, for example Ollama) can: it depends on the model. */
function blocked(
  targetTools: boolean | null | undefined,
  engine: string | undefined,
  isViewer: boolean
): string {
  if (isViewer) return "Viewers cannot run tools.";
  if (targetTools !== false) return "";
  return engine === "vLLM"
    ? "This vLLM instance has Tool calling off."
    : "This model does not support tool calls.";
}

function serverNote(server: McpServer): string {
  if (!server.enabled) return "disabled";
  if (server.deploy && !server.deploy.usable)
    return server.deploy.status === "Failed" ? "failed" : "starting";
  if (server.status !== "connected") return "unreachable";
  if (server.my_credential === "missing")
    return server.oauth ? "needs your sign-in" : "needs your credential";
  const count = allowedTools(server).length;
  const asks =
    server.approval === "always"
      ? " · asks first"
      : server.approval === "writes"
        ? " · asks before changes"
        : "";
  return `${count} ${count === 1 ? "tool" : "tools"}${asks}`;
}

/**
 * The MCP servers the next request may use. A switch per server; the
 * choice stays when the section is blocked, so a change of target does
 * not lose it.
 */
export function ChatTools({
  servers,
  selected,
  active,
  onToggle,
  targetTools,
  engine,
  settingsHref,
  isViewer,
  isAdmin,
  onConnect,
  askFirst,
  onAskFirstChange,
  functions,
  onFunctionToggle,
  onFunctionEdit,
  budget,
}: {
  /** Functions typed in the playground (nothing runs; the user types
      the result). */
  functions: { name: string; enabled: boolean }[];
  onFunctionToggle: (name: string, on: boolean) => void;
  /** null: add a new one. */
  onFunctionEdit: (name: string | null) => void;
  /** Ask before each tool call. */
  askFirst: boolean;
  onAskFirstChange: (on: boolean) => void;
  /** Open the dialog for the caller's own credential. */
  onConnect?: (server: McpServer) => void;
  servers: McpServer[];
  selected: string[];
  /** The selected servers a request can carry right now. */
  active: string[];
  onToggle: (name: string, on: boolean) => void;
  targetTools: boolean | null | undefined;
  engine: string | undefined;
  /** Where Tool calling is turned on, for a vLLM instance. */
  settingsHref?: string;
  isViewer: boolean;
  isAdmin: boolean;
  /** What the tools that are on take of the target's window. */
  budget?: ToolBudget;
}) {
  const reason = blocked(targetTools, engine, isViewer);
  return (
    <div className="space-y-2" role="group" aria-label="Tools">
      <div className="flex items-center justify-between">
        <span className="text-sm leading-none font-medium">Tools</span>
        {!reason && active.length > 0 && (
          <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
            {active.length} on
          </span>
        )}
      </div>
      {reason && (
        <p
          className="text-xs text-muted-foreground"
          data-testid="tools-blocked"
        >
          {reason}{" "}
          {!isViewer && engine === "vLLM" && settingsHref && (
            <Link href={settingsHref} className="underline">
              Turn it on in Edit settings
            </Link>
          )}
        </p>
      )}
      {!reason && budget && budget.tools > 0 && (
        <p
          data-testid="tools-budget"
          role={budget.warn ? "alert" : undefined}
          className={
            budget.warn
              ? "rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200"
              : "text-xs text-muted-foreground"
          }
        >
          {budget.tools} {budget.tools === 1 ? "tool" : "tools"}, about{" "}
          {budget.tokens.toLocaleString("en-US")} tokens
          {budget.share !== null &&
            ` (${Math.round(budget.share * 100)}% of this model's window)`}
          .
          {budget.warn && (
            <>
              {" "}
              The definitions go with every step, so little room stays for the
              conversation.
              {budget.largest && ` Most of it is ${budget.largest.name}.`}{" "}
              {isAdmin
                ? "Limit its tools (MCP page, Edit tools) or turn a server off."
                : "Turn a server off, or ask an admin to limit its tools."}
            </>
          )}
        </p>
      )}
      {!reason && targetTools == null && servers.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Not every model can call tools. If the answer ignores them, try
          another model.
        </p>
      )}
      {servers.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          No MCP servers.{" "}
          {isAdmin ? (
            <Link href="/mcp-servers" className="underline">
              Add one
            </Link>
          ) : (
            "Ask an organization admin to add one."
          )}
        </p>
      ) : (
        <ul className="space-y-1">
          {servers.map((server) => (
            <li
              key={server.id}
              className="flex items-center justify-between gap-2 text-sm"
            >
              <span className="min-w-0 truncate">
                {server.name}{" "}
                <span className="text-xs text-muted-foreground">
                  {serverNote(server)}
                </span>
              </span>
              {server.my_credential === "missing" &&
              server.enabled &&
              !isViewer &&
              onConnect ? (
                <button
                  type="button"
                  className="text-xs font-medium underline"
                  aria-label={`Connect ${server.name}`}
                  onClick={() => onConnect(server)}
                >
                  Connect
                </button>
              ) : null}
              <Switch
                aria-label={`Use ${server.name}`}
                checked={selected.includes(server.name)}
                disabled={!!reason || !usable(server)}
                onCheckedChange={(on) => onToggle(server.name, on)}
              />
            </li>
          ))}
        </ul>
      )}
      {servers.length > 0 && (
        <div className="flex items-center justify-between gap-2 pt-1 text-sm">
          <span>
            Ask before each call{" "}
            <span className="block text-xs text-muted-foreground">
              A tool can change data. You see the call and its input first.
            </span>
          </span>
          <Switch
            aria-label="Ask before each tool call"
            checked={askFirst}
            disabled={!!reason}
            onCheckedChange={onAskFirstChange}
          />
        </div>
      )}
      {servers.length > 0 && (
        <Link
          href="/mcp-servers"
          className="block text-xs text-muted-foreground underline"
        >
          Manage MCP servers
        </Link>
      )}
      <div className="space-y-1 pt-2" role="group" aria-label="Functions">
        <div className="flex items-center justify-between">
          <span className="text-sm leading-none font-medium">Functions</span>
          <button
            type="button"
            className="text-xs font-medium underline"
            onClick={() => onFunctionEdit(null)}
          >
            Add function
          </button>
        </div>
        {functions.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            Try a function-calling prompt: the model calls your function, you
            type the result.
          </p>
        ) : (
          <ul className="space-y-1">
            {functions.map((fn) => (
              <li
                key={fn.name}
                className="flex items-center justify-between gap-2 text-sm"
              >
                <button
                  type="button"
                  className="min-w-0 truncate font-mono text-xs underline"
                  aria-label={`Edit ${fn.name}`}
                  onClick={() => onFunctionEdit(fn.name)}
                >
                  {fn.name}
                </button>
                <Switch
                  aria-label={`Use function ${fn.name}`}
                  checked={fn.enabled}
                  disabled={!!reason}
                  onCheckedChange={(on) => onFunctionToggle(fn.name, on)}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
