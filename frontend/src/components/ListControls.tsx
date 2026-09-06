"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type StatusFilter = "all" | "ready" | "pending";
export type SortKey = "name-asc" | "name-desc" | "status";
export type ListState = { status: StatusFilter; sort: SortKey; page: number };
export const PAGE_SIZE = 12;

export function useListState(): [
  ListState,
  (patch: Partial<ListState>) => void,
] {
  const [state, setState] = useState<ListState>({
    status: "all",
    sort: "name-asc",
    page: 1,
  });
  // Any filter or sort change goes back to the first page.
  const update = (patch: Partial<ListState>) =>
    setState((s) => ({ ...s, ...patch, page: patch.page ?? 1 }));
  return [state, update];
}

export function applyListControls<T>(
  items: T[],
  state: ListState,
  opts: { name: (item: T) => string; ready: (item: T) => boolean }
): { visible: T[]; total: number; hasMore: boolean } {
  const filtered = items.filter((i) =>
    state.status === "all"
      ? true
      : state.status === "ready"
        ? opts.ready(i)
        : !opts.ready(i)
  );
  const sorted = [...filtered].sort((a, b) => {
    if (state.sort === "status") {
      const d = Number(opts.ready(b)) - Number(opts.ready(a));
      if (d !== 0) return d;
    }
    const cmp = opts.name(a).localeCompare(opts.name(b));
    return state.sort === "name-desc" ? -cmp : cmp;
  });
  const visible = sorted.slice(0, state.page * PAGE_SIZE);
  return {
    visible,
    total: sorted.length,
    hasMore: visible.length < sorted.length,
  };
}

export function ListControls({
  state,
  onChange,
}: {
  state: ListState;
  onChange: (patch: Partial<ListState>) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <Select
        value={state.status}
        onValueChange={(v) => onChange({ status: v as StatusFilter })}
      >
        <SelectTrigger className="w-[150px]" aria-label="Status">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All</SelectItem>
          <SelectItem value="ready">Ready</SelectItem>
          <SelectItem value="pending">Not ready</SelectItem>
        </SelectContent>
      </Select>
      <Select
        value={state.sort}
        onValueChange={(v) => onChange({ sort: v as SortKey })}
      >
        <SelectTrigger className="w-[150px]" aria-label="Sort">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="name-asc">Name A-Z</SelectItem>
          <SelectItem value="name-desc">Name Z-A</SelectItem>
          <SelectItem value="status">Status</SelectItem>
        </SelectContent>
      </Select>
    </div>
  );
}

export function ShowMore({
  hasMore,
  onClick,
  shown,
  total,
}: {
  hasMore: boolean;
  onClick: () => void;
  shown: number;
  total: number;
}) {
  if (total === 0 || !hasMore) return null;
  return (
    <div className="mt-6 flex justify-center">
      <Button variant="outline" onClick={onClick} disabled={!hasMore}>
        Show more ({shown} of {total})
      </Button>
    </div>
  );
}
