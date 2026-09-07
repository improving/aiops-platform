"use client";

import { useCallback, useMemo, useState } from "react";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CopyButton } from "@/components/CopyButton";
import { RefreshButton } from "@/components/RefreshButton";
import { TableSkeleton } from "@/components/LoadingState";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";
import { useLatestRequest } from "@/hooks/useLatestRequest";
import { LogsQuery, PodLogs } from "@/types/models";

const TAIL_OPTIONS = [200, 1000, 5000];

/**
 * The logs of every pod behind an instance. `fetchLogs` is the service
 * call of the instance kind (wrap it in useCallback: it is an effect
 * dependency). Every container is fetched at once; the combobox picks
 * which one is shown.
 */
export function LogsPanel({
  fetchLogs,
}: {
  fetchLogs: (query: LogsQuery) => Promise<PodLogs>;
}) {
  const [tail, setTail] = useState(200);
  const [previous, setPrevious] = useState(false);
  const [selected, setSelected] = useState("");
  const { toast } = useToast();

  const fetchCurrent = useCallback(
    () => fetchLogs({ tail, previous }),
    [fetchLogs, tail, previous]
  );
  const onFetchError = useCallback(
    (error: unknown) => toast(parseApiError(error)),
    [toast]
  );
  const {
    data: logs,
    loading,
    reload: load,
  } = useLatestRequest(fetchCurrent, onFetchError);

  // "<pod>/<container>" for every container, in API order.
  const targets = useMemo(
    () =>
      (logs?.pods ?? []).flatMap((pod) =>
        pod.containers.map((container) => ({
          key: `${pod.name}/${container.name}`,
          log: container.log,
        }))
      ),
    [logs]
  );
  const current = targets.find((t) => t.key === selected) ?? targets[0];

  if (loading) return <TableSkeleton rows={6} columns={1} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <div className="grid gap-1">
          <Label htmlFor="log-container">Container</Label>
          <Select value={current?.key ?? ""} onValueChange={setSelected}>
            <SelectTrigger
              id="log-container"
              aria-label="Container"
              className="w-[280px]"
            >
              <SelectValue placeholder="No pods" />
            </SelectTrigger>
            <SelectContent>
              {targets.map((target) => (
                <SelectItem key={target.key} value={target.key}>
                  {target.key}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="log-tail">Lines</Label>
          <Select
            value={String(tail)}
            onValueChange={(value) => setTail(Number(value))}
          >
            <SelectTrigger
              id="log-tail"
              aria-label="Lines"
              className="w-[120px]"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TAIL_OPTIONS.map((n) => (
                <SelectItem key={n} value={String(n)}>
                  {n}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2 pb-2">
          <Switch
            id="log-previous"
            checked={previous}
            onCheckedChange={setPrevious}
          />
          <Label htmlFor="log-previous">Previous</Label>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {current && <CopyButton label="log" text={current.log} />}
          <RefreshButton onRefresh={load} />
        </div>
      </div>
      {current ? (
        <pre
          role="group"
          aria-label="Log output"
          className="max-h-[60vh] overflow-auto rounded-md bg-muted p-3 font-mono text-xs whitespace-pre-wrap"
        >
          {current.log || "(empty)"}
        </pre>
      ) : (
        <p className="text-sm text-muted-foreground">No pods found.</p>
      )}
    </div>
  );
}
