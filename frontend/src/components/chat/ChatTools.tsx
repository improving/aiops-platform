"use client";

import { useState } from "react";
import Link from "next/link";
import { Cross2Icon, MixerHorizontalIcon } from "@radix-ui/react-icons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
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

/** Chips next to the button, before "+N". */
const MAX_CHIPS = 3;

/**
 * The tools of the next request, where a message is written: one button
 * in the composer's row, the servers and functions that are on as chips
 * next to it, and a popover with everything else. The list is searched
 * and grouped (on, available, needs attention), so it reads the same
 * with five servers and with fifty. The choice stays when the tools are
 * blocked for a target, so a change of target does not lose it.
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
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const reason = blocked(targetTools, engine, isViewer);
  const needle = filter.trim().toLowerCase();
  const match = (name: string) =>
    !needle || name.toLowerCase().includes(needle);

  const needsMe = (server: McpServer) =>
    server.enabled && server.my_credential === "missing";
  const on = servers.filter((s) => selected.includes(s.name) && usable(s));
  const attention = servers.filter((s) => !usable(s));
  const available = servers.filter(
    (s) => usable(s) && !selected.includes(s.name)
  );
  const functionsOn = reason ? [] : functions.filter((f) => f.enabled);
  const chips = [
    ...active.map((name) => ({
      key: `s:${name}`,
      label: name,
      off: () => onToggle(name, false),
    })),
    ...functionsOn.map((fn) => ({
      key: `f:${fn.name}`,
      label: fn.name,
      off: () => onFunctionToggle(fn.name, false),
    })),
  ];
  const count = chips.length;

  const row = (server: McpServer) => (
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
      <span className="flex shrink-0 items-center gap-2">
        {needsMe(server) && !isViewer && onConnect ? (
          <button
            type="button"
            className="text-xs font-medium underline"
            aria-label={`Connect ${server.name}`}
            onClick={() => {
              setOpen(false);
              onConnect(server);
            }}
          >
            Connect
          </button>
        ) : null}
        <Switch
          aria-label={`Use ${server.name}`}
          checked={selected.includes(server.name)}
          disabled={!!reason || !usable(server)}
          onCheckedChange={(checked) => onToggle(server.name, checked)}
        />
      </span>
    </li>
  );

  const group = (title: string, items: McpServer[]) => {
    const shown = items.filter((s) => match(s.name));
    if (shown.length === 0) return null;
    return (
      <div className="space-y-1">
        <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
          {title}
        </p>
        <ul className="space-y-1.5">{shown.map(row)}</ul>
      </div>
    );
  };

  return (
    <div className="flex min-w-0 items-center gap-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className={
              budget?.warn && !reason
                ? "h-7 gap-1.5 border-amber-400 px-2 text-xs text-amber-700 dark:text-amber-300"
                : "h-7 gap-1.5 px-2 text-xs"
            }
          >
            <MixerHorizontalIcon aria-hidden className="h-3.5 w-3.5" />
            Tools
            {count > 0 && (
              <span className="rounded-full bg-primary/10 px-1.5 text-[11px] font-medium text-primary">
                {count}
              </span>
            )}
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          side="top"
          className="max-h-[min(32rem,70vh)] w-[22rem] overflow-y-auto p-3"
        >
          <div className="space-y-3" role="group" aria-label="Tools">
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
                    The definitions go with every step, so little room stays for
                    the conversation.
                    {budget.largest &&
                      ` Most of it is ${budget.largest.name}.`}{" "}
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
              <>
                {servers.length + functions.length > 5 && (
                  <Input
                    aria-label="Search tools"
                    placeholder="Search servers and functions…"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    className="h-8 text-sm"
                  />
                )}
                {group("On", on)}
                {group("Available", available)}
                {group("Needs attention", attention)}
              </>
            )}
            <div className="space-y-1" role="group" aria-label="Functions">
              <div className="flex items-center justify-between">
                <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                  Functions
                </p>
                <button
                  type="button"
                  className="text-xs font-medium underline"
                  onClick={() => {
                    setOpen(false);
                    onFunctionEdit(null);
                  }}
                >
                  Add function
                </button>
              </div>
              {functions.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  Try a function-calling prompt: the model calls your function,
                  you type the result.
                </p>
              ) : (
                <ul className="space-y-1.5">
                  {functions
                    .filter((fn) => match(fn.name))
                    .map((fn) => (
                      <li
                        key={fn.name}
                        className="flex items-center justify-between gap-2 text-sm"
                      >
                        <button
                          type="button"
                          className="min-w-0 truncate font-mono text-xs underline"
                          aria-label={`Edit ${fn.name}`}
                          onClick={() => {
                            setOpen(false);
                            onFunctionEdit(fn.name);
                          }}
                        >
                          {fn.name}
                        </button>
                        <Switch
                          aria-label={`Use function ${fn.name}`}
                          checked={fn.enabled}
                          disabled={!!reason}
                          onCheckedChange={(checked) =>
                            onFunctionToggle(fn.name, checked)
                          }
                        />
                      </li>
                    ))}
                </ul>
              )}
            </div>
            {servers.length > 0 && (
              <Link
                href="/mcp-servers"
                className="block text-xs text-muted-foreground underline"
              >
                Manage MCP servers
              </Link>
            )}
          </div>
        </PopoverContent>
      </Popover>

      {/* What is on, and one click to turn it off. */}
      {count > 0 && (
        <ul
          aria-label="Tools that are on"
          className="flex min-w-0 items-center gap-1 overflow-hidden"
        >
          {chips.slice(0, MAX_CHIPS).map((chip) => (
            <li
              key={chip.key}
              className="flex items-center gap-0.5 rounded-full bg-muted py-0.5 pr-1 pl-2 text-xs"
            >
              <span className="max-w-[8rem] truncate">{chip.label}</span>
              <button
                type="button"
                aria-label={`Turn off ${chip.label}`}
                className="rounded-full p-0.5 text-muted-foreground hover:text-foreground"
                onClick={chip.off}
              >
                <Cross2Icon aria-hidden className="h-3 w-3" />
              </button>
            </li>
          ))}
          {count > MAX_CHIPS && (
            <li className="text-xs text-muted-foreground">
              +{count - MAX_CHIPS}
            </li>
          )}
        </ul>
      )}
      {active.length > 0 && (
        <span data-testid="chat-tools-on" className="sr-only">
          {active.length} {active.length === 1 ? "tool server" : "tool servers"}{" "}
          on
        </span>
      )}
    </div>
  );
}
