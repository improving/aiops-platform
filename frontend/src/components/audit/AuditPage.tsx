"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DownloadIcon } from "@radix-ui/react-icons";
import { useToast } from "@/components/hooks/use-toast";
import { TableSkeleton } from "@/components/LoadingState";
import {
  applyListControls,
  ShowMore,
  useListState,
} from "@/components/ListControls";
import { useOrg } from "@/hooks/useOrg";
import { downloadTextFile } from "@/lib/csv";
import { parseApiError } from "@/lib/utils";
import { auditService } from "@/services/auditService";
import type { AuditEvent, AuditFilters } from "@/types/organization";

// backend/audit/events.py: the actions the middleware and routers write.
const ACTIONS = [
  "create",
  "update",
  "delete",
  "reveal",
  "restart",
  "stop",
  "resume",
  "scale",
];
const ALL = "all";
const PAGE_LIMIT = 100;

function formatAt(value: string): string {
  return new Date(value).toLocaleString();
}

// /audit (spec 5.3): filters, the table, "Show more" through ListControls
// (local pages of 12 over the fetched rows, then the API's cursor) and
// "Export CSV" through the endpoint's `format=csv`.
export default function AuditPage() {
  const { toast } = useToast();
  const { isAdmin, loading: orgLoading } = useOrg();
  const [draft, setDraft] = useState<AuditFilters>({});
  const [filters, setFilters] = useState<AuditFilters>({});
  const [action, setAction] = useState(ALL);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [state, update, nextPage] = useListState();

  const fetchEvents = useCallback(
    async (query: AuditFilters, cursor: string | null) => {
      try {
        const pageData = await auditService.list({
          ...query,
          limit: PAGE_LIMIT,
          cursor: cursor ?? undefined,
        });
        setEvents((prev) =>
          cursor ? [...prev, ...pageData.events] : pageData.events
        );
        setNextCursor(pageData.next_cursor);
      } catch (error) {
        toast(parseApiError(error));
      } finally {
        setLoading(false);
      }
    },
    [toast]
  );

  useEffect(() => {
    if (orgLoading) return;
    (async () => {
      if (isAdmin) {
        await fetchEvents(filters, null);
      } else {
        setLoading(false);
      }
    })();
  }, [orgLoading, isAdmin, filters, fetchEvents]);

  const apply = () => {
    // Back to the skeleton so a spec's waitForLoaded() sees the new list.
    setLoading(true);
    setFilters({
      ...draft,
      // The backend compares `to` with `<=`; include the whole day.
      to: draft.to ? `${draft.to}T23:59:59` : undefined,
      action: action === ALL ? undefined : action,
    });
    update({ page: 1 });
  };

  const { visible, total, hasMore } = applyListControls(events, state, {
    name: (e) => e.actor_label,
    sortKey: (e) => Date.parse(e.at),
    direction: "desc",
  });

  const showMore = async () => {
    if (!hasMore && nextCursor) {
      await fetchEvents(filters, nextCursor);
    }
    nextPage();
  };

  const exportCsv = async () => {
    setExporting(true);
    try {
      // The export ignores `limit` and pages through every matching row
      // itself, up to its own hard cap (backend/api/audit.py CSV_ROW_CAP).
      const text = await auditService.exportCsv(filters);
      downloadTextFile("audit.csv", text);
      if (text.trimEnd().endsWith("# truncated")) {
        toast({
          title: "Export truncated",
          description: "The export stopped at 100000 rows; narrow the filters",
        });
      }
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setExporting(false);
    }
  };

  if (orgLoading || loading) {
    return <TableSkeleton rows={8} columns={7} />;
  }
  if (!isAdmin) {
    return (
      <p className="text-muted-foreground">
        Only organization admins can view the audit log.
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="audit-from">From</Label>
          <Input
            id="audit-from"
            type="date"
            value={draft.from ?? ""}
            onChange={(e) => setDraft({ ...draft, from: e.target.value })}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="audit-to">To</Label>
          <Input
            id="audit-to"
            type="date"
            value={draft.to ?? ""}
            onChange={(e) => setDraft({ ...draft, to: e.target.value })}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="audit-actor">Actor</Label>
          <Input
            id="audit-actor"
            value={draft.actor ?? ""}
            onChange={(e) => setDraft({ ...draft, actor: e.target.value })}
            placeholder="email, svc:, token:"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="audit-action">Action</Label>
          <Select value={action} onValueChange={setAction}>
            <SelectTrigger
              id="audit-action"
              className="w-[140px]"
              aria-label="Action"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All actions</SelectItem>
              {ACTIONS.map((a) => (
                <SelectItem key={a} value={a}>
                  {a}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="audit-kind">Kind</Label>
          <Input
            id="audit-kind"
            value={draft.resource_kind ?? ""}
            onChange={(e) =>
              setDraft({ ...draft, resource_kind: e.target.value })
            }
            placeholder="inferenceInstance"
          />
        </div>
        <Button onClick={apply}>Apply</Button>
        <Button
          variant="outline"
          onClick={exportCsv}
          loading={exporting}
          icon={<DownloadIcon className="w-4 h-4" />}
        >
          Export CSV
        </Button>
      </div>

      <Table>
        <TableCaption>Audit events</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>At</TableHead>
            <TableHead>Actor</TableHead>
            <TableHead>Action</TableHead>
            <TableHead>Kind</TableHead>
            <TableHead>Resource</TableHead>
            <TableHead>Outcome</TableHead>
            <TableHead>Request id</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {visible.length === 0 ? (
            <TableRow>
              <TableCell colSpan={7} className="text-muted-foreground">
                No events match.
              </TableCell>
            </TableRow>
          ) : (
            visible.map((event) => (
              <TableRow key={event.id}>
                <TableCell>{formatAt(event.at)}</TableCell>
                <TableCell>{event.actor_label}</TableCell>
                <TableCell>{event.action}</TableCell>
                <TableCell>{event.resource_kind}</TableCell>
                <TableCell className="font-mono text-xs">
                  {event.resource_id ?? "—"}
                </TableCell>
                <TableCell>{event.outcome}</TableCell>
                <TableCell className="font-mono text-xs">
                  {event.request_id ?? "—"}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      <ShowMore
        hasMore={hasMore || nextCursor !== null}
        onClick={showMore}
        shown={visible.length}
        total={total}
      />
    </div>
  );
}
