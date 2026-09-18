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
import {
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { RefreshButton } from "@/components/RefreshButton";
import { TableSkeleton } from "@/components/LoadingState";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";
import { useLatestRequest } from "@/hooks/useLatestRequest";
import { InstanceEvent } from "@/types/models";

// The API returns at most 100 events (backend/utils/pod_inspection.py
// MAX_EVENTS), newest first; the panel shows the newest `limit` of them.
const LIMIT_OPTIONS = [25, 50, 100];

/**
 * The Kubernetes events of an instance's pods and workload, newest first,
 * in a scroll area with a fixed header, like the log view: a restart loop
 * writes dozens of events, and the list must not grow the page.
 */
export function EventsPanel({
  fetchEvents,
}: {
  fetchEvents: () => Promise<InstanceEvent[]>;
}) {
  const [limit, setLimit] = useState(LIMIT_OPTIONS[0]);
  const [warningsOnly, setWarningsOnly] = useState(false);
  const { toast } = useToast();
  const onFetchError = useCallback(
    (error: unknown) => toast(parseApiError(error)),
    [toast]
  );
  const {
    data: events,
    loading,
    reload: load,
  } = useLatestRequest(fetchEvents, onFetchError);

  const matching = useMemo(
    () =>
      (events ?? []).filter(
        (event) => !warningsOnly || event.type === "Warning"
      ),
    [events, warningsOnly]
  );
  const visible = matching.slice(0, limit);

  if (loading) return <TableSkeleton rows={5} columns={5} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <div className="grid gap-1">
          <Label htmlFor="events-limit">Events</Label>
          <Select
            value={String(limit)}
            onValueChange={(value) => setLimit(Number(value))}
          >
            <SelectTrigger
              id="events-limit"
              aria-label="Events shown"
              className="w-[120px]"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LIMIT_OPTIONS.map((n) => (
                <SelectItem key={n} value={String(n)}>
                  {n}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2 pb-2">
          <Switch
            id="events-warnings"
            checked={warningsOnly}
            onCheckedChange={setWarningsOnly}
          />
          <Label htmlFor="events-warnings">Warnings only</Label>
        </div>
        <p
          data-slot="events-count"
          className="pb-2 text-sm text-muted-foreground"
        >
          {visible.length} of {matching.length}, newest first
        </p>
        <div className="ml-auto">
          <RefreshButton onRefresh={load} />
        </div>
      </div>
      {/* A plain table in a scroll area of its own: the shared Table wraps
          itself in an overflow-x container, which a sticky header would
          stick to instead of this one. */}
      <div className="max-h-[60vh] overflow-auto rounded-md border">
        <table className="w-full text-sm">
          <TableCaption className="sr-only">Events</TableCaption>
          <TableHeader className="sticky top-0 z-10 bg-background">
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Reason</TableHead>
              <TableHead>Object</TableHead>
              <TableHead>Message</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {visible.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground">
                  {warningsOnly ? "No warnings." : "No events."}
                </TableCell>
              </TableRow>
            ) : (
              visible.map((event, index) => (
                <TableRow key={`${event.object}-${event.at}-${index}`}>
                  <TableCell className="whitespace-nowrap">
                    {event.at ? new Date(event.at).toLocaleString() : "-"}
                  </TableCell>
                  <TableCell
                    className={
                      event.type === "Warning"
                        ? "font-medium text-amber-700 dark:text-amber-400"
                        : undefined
                    }
                  >
                    {event.type}
                  </TableCell>
                  <TableCell>{event.reason}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {event.object}
                  </TableCell>
                  <TableCell className="break-words">{event.message}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </table>
      </div>
    </div>
  );
}
