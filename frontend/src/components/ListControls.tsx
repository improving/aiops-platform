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

export const STATUS_OPTIONS = [
  { value: "all", label: "All" },
  { value: "ready", label: "Ready" },
  { value: "pending", label: "Not ready" },
] as const;
export const SORT_OPTIONS = [
  { value: "name-asc", label: "Name A-Z" },
  { value: "name-desc", label: "Name Z-A" },
  { value: "status", label: "Status" },
] as const;

export type StatusFilter = (typeof STATUS_OPTIONS)[number]["value"];
export type SortKey = (typeof SORT_OPTIONS)[number]["value"];
export type ListState = { status: StatusFilter; sort: SortKey; page: number };
export const PAGE_SIZE = 12;

export function useListState(): [
  ListState,
  (patch: Partial<ListState>) => void,
  () => void,
] {
  const [state, setState] = useState<ListState>({
    status: "all",
    sort: "name-asc",
    page: 1,
  });
  // Any filter or sort change goes back to the first page.
  const update = (patch: Partial<ListState>) =>
    setState((s) => ({ ...s, ...patch, page: patch.page ?? 1 }));
  const nextPage = () => setState((s) => ({ ...s, page: s.page + 1 }));
  return [state, update, nextPage];
}

const DEFAULT_SORT: SortKey = "name-asc";

export function applyListControls<T>(
  items: T[],
  state: ListState,
  opts: {
    name: (item: T) => string;
    ready?: (item: T) => boolean;
    // Overrides the default name sort while `state.sort` is still at its
    // default (a caller with no readiness concept, like the audit log,
    // has no `ListControls` to pick a different sort from anyway).
    sortKey?: (item: T) => string | number;
    direction?: "asc" | "desc";
  }
): { visible: T[]; total: number; hasMore: boolean } {
  const filtered = !opts.ready
    ? items
    : items.filter((i) =>
        state.status === "all"
          ? true
          : state.status === "ready"
            ? opts.ready!(i)
            : !opts.ready!(i)
      );
  const sorted = [...filtered].sort((a, b) => {
    if (state.sort === "status" && opts.ready) {
      const d = Number(opts.ready(b)) - Number(opts.ready(a));
      if (d !== 0) return d;
    }
    if (state.sort === DEFAULT_SORT && opts.sortKey) {
      const ka = opts.sortKey(a);
      const kb = opts.sortKey(b);
      const cmp = ka < kb ? -1 : ka > kb ? 1 : 0;
      return opts.direction === "desc" ? -cmp : cmp;
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
  showStatusFilter = true,
}: {
  state: ListState;
  onChange: (patch: Partial<ListState>) => void;
  // False for a list with no readiness concept (MembersTable): the Status
  // filter has nothing to filter, so it does not render, and the Sort
  // options drop "Status" too -- it would silently order like "Name A-Z".
  showStatusFilter?: boolean;
}) {
  const sortOptions = showStatusFilter
    ? SORT_OPTIONS
    : SORT_OPTIONS.filter((option) => option.value !== "status");
  return (
    <div className="flex flex-wrap gap-2">
      {showStatusFilter && (
        <Select
          value={state.status}
          onValueChange={(v) => {
            const option = STATUS_OPTIONS.find((o) => o.value === v);
            if (option) onChange({ status: option.value });
          }}
        >
          <SelectTrigger className="w-[150px]" aria-label="Status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      <Select
        value={state.sort}
        onValueChange={(v) => {
          const option = sortOptions.find((o) => o.value === v);
          if (option) onChange({ sort: option.value });
        }}
      >
        <SelectTrigger className="w-[150px]" aria-label="Sort">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {sortOptions.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
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
