import Link from "next/link";
import { Switch } from "@/components/ui/switch";
import { allowedTools, usable, type McpServer } from "@/types/mcp";

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
  if (server.status !== "connected") return "unreachable";
  if (server.my_credential === "missing") return "needs your credential";
  const count = allowedTools(server).length;
  return `${count} ${count === 1 ? "tool" : "tools"}`;
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
}: {
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
        <Link
          href="/mcp-servers"
          className="block text-xs text-muted-foreground underline"
        >
          Manage MCP servers
        </Link>
      )}
    </div>
  );
}
