"use client";

import { useEffect } from "react";

const DEFAULT_POLL_INTERVAL_MS = 5000;

const TERMINAL_STATUSES = new Set(["Running", "Ready", "Failed"]);

/**
 * An item is still being provisioned (and worth polling for) until it both
 * has an endpoint and has settled into a terminal status. A "Failed" item
 * with no endpoint is terminal too -- it isn't going to get one.
 */
export function isNonTerminal(item: {
  endpoint?: string | null;
  status?: string | null;
  ready?: boolean;
}): boolean {
  if (item.ready) return false;
  if (item.status && TERMINAL_STATUSES.has(item.status)) return false;
  return true;
}

/**
 * Calls `callback` every `intervalMs` while `enabled` is true, and stops
 * (clearing the interval) as soon as `enabled` becomes false or the
 * component unmounts. Pass a stable (useCallback'd) `callback` so the
 * interval isn't torn down and restarted on every render.
 */
export function usePolling(
  callback: () => void,
  enabled: boolean,
  intervalMs: number = DEFAULT_POLL_INTERVAL_MS
) {
  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(callback, intervalMs);
    return () => clearInterval(id);
  }, [callback, enabled, intervalMs]);
}
