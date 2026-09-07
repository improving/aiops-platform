"use client";

import { useCallback } from "react";
import {
  Table,
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

/** The Kubernetes events of an instance's pods and workload, newest first. */
export function EventsPanel({
  fetchEvents,
}: {
  fetchEvents: () => Promise<InstanceEvent[]>;
}) {
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

  if (loading) return <TableSkeleton rows={5} columns={5} />;

  const visible = events ?? [];

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <RefreshButton onRefresh={load} />
      </div>
      <Table>
        <TableCaption>Events</TableCaption>
        <TableHeader>
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
                No events.
              </TableCell>
            </TableRow>
          ) : (
            visible.map((event, index) => (
              <TableRow key={`${event.object}-${event.at}-${index}`}>
                <TableCell className="whitespace-nowrap">
                  {event.at ? new Date(event.at).toLocaleString() : "-"}
                </TableCell>
                <TableCell>{event.type}</TableCell>
                <TableCell>{event.reason}</TableCell>
                <TableCell className="font-mono text-xs">
                  {event.object}
                </TableCell>
                <TableCell className="break-all">{event.message}</TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
