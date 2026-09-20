import { useCallback, useEffect, useMemo, useState } from "react";
import { mcpService } from "@/services/mcpService";
import { usable, type McpServer } from "@/types/mcp";

const KEY_PREFIX = "aiops.chat.tools.";

function storageKey(userKey: string): string {
  return `${KEY_PREFIX}${encodeURIComponent(userKey)}`;
}

function load(userKey: string): string[] {
  try {
    const raw = localStorage.getItem(storageKey(userKey));
    const value: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(value)
      ? value.filter((v): v is string => typeof v === "string")
      : [];
  } catch {
    return [];
  }
}

function save(userKey: string, names: string[]): void {
  try {
    localStorage.setItem(storageKey(userKey), JSON.stringify(names));
  } catch {
    // A full or blocked storage only loses the convenience.
  }
}

/**
 * The organization's MCP servers and which of them this user has turned
 * on for Chat. The choice is the user's and the browser's, kept across
 * targets; `preselect` (the `?tools=` of a "Try in chat" link) adds to
 * it. A failed fetch (no LiteLLM, no permission) is an empty list: the
 * chat works without tools.
 */
export function useToolServers(userKey: string, preselect: string[]) {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const wanted = preselect.join(",");

  useEffect(() => {
    (async () => {
      const listed = await mcpService.getServers().catch(() => []);
      setServers(listed);
    })();
  }, []);

  // localStorage is the browser's: read it after mount, never in render.
  useEffect(() => {
    (async () => {
      const added = wanted ? wanted.split(",") : [];
      const merged = [...new Set([...load(userKey), ...added])];
      setSelected(merged);
      if (added.length > 0) save(userKey, merged);
    })();
  }, [userKey, wanted]);

  const toggle = useCallback(
    (name: string, on: boolean) => {
      setSelected((current) => {
        const next = on
          ? [...new Set([...current, name])]
          : current.filter((n) => n !== name);
        save(userKey, next);
        return next;
      });
    },
    [userKey]
  );

  // What a request can carry: a name that is still a usable server.
  const active = useMemo(
    () =>
      servers
        .filter((s) => usable(s) && selected.includes(s.name))
        .map((s) => s.name),
    [servers, selected]
  );

  // One server changed (the caller connected their credential).
  const replace = useCallback((server: McpServer) => {
    setServers((current) =>
      current.map((s) => (s.id === server.id ? server : s))
    );
  }, []);

  return { servers, selected, active, toggle, replace };
}
