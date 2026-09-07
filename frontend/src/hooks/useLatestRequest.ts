"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Runs `fetcher` on mount and on every `reload()`, keeping only the
 * result of the most recently started call.
 *
 * This guards components that stay mounted across a navigation between
 * two instances of the same kind (the instance detail panels are not
 * keyed by instance id): without it, a slow response for the previous
 * instance could overwrite the panel with stale data after a newer
 * request has already started. A request bumps a ref before awaiting; a
 * response only applies -- to `data`, `error` or `loading` -- if no
 * newer request has started meanwhile.
 *
 * `onError` is read through a ref, so callers can pass an inline closure
 * without it forcing a reload on every render.
 */
export function useLatestRequest<T>(
  fetcher: () => Promise<T>,
  onError?: (error: unknown) => void
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const requestIdRef = useRef(0);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  const reload = useCallback(async () => {
    const requestId = ++requestIdRef.current;
    try {
      const result = await fetcher();
      if (requestIdRef.current === requestId) {
        setData(result);
        setError(null);
      }
    } catch (err) {
      if (requestIdRef.current === requestId) {
        setError(err);
        onErrorRef.current?.(err);
      }
    } finally {
      if (requestIdRef.current === requestId) setLoading(false);
    }
  }, [fetcher]);

  useEffect(() => {
    (async () => {
      await reload();
    })();
  }, [reload]);

  return { data, error, loading, reload };
}
