"use client";

import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { parseApiError } from "@/lib/utils";
import { usageService } from "@/services/usageService";
import type { OrgUsage } from "@/types/models";
import { TableSkeleton } from "@/components/LoadingState";

// Period select values are `days` for GET
// /v1alpha1/organizations/current/usage?days= (backend/api/organizations.py,
// clamped 1..90; 30 is its default).
const PERIODS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
];

function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`;
}

interface StatCardProps {
  title: string;
  value: string;
  testId: string;
}

function StatCard({ title, value, testId }: StatCardProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-bold" data-testid={testId}>
          {value}
        </p>
      </CardContent>
    </Card>
  );
}

export default function UsagePage() {
  const [days, setDays] = useState("30");
  const [usage, setUsage] = useState<OrgUsage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchUsage = useCallback(async (period: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await usageService.getUsage(Number(period));
      setUsage(data);
    } catch (err) {
      setUsage(null);
      const description = parseApiError(err).description;
      setError(
        typeof description === "string" && description
          ? description
          : "Failed to load usage."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsage(days);
  }, [days, fetchUsage]);

  return (
    <div className="space-y-6">
      <Select value={days} onValueChange={setDays}>
        <SelectTrigger className="w-[180px]" aria-label="Period">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PERIODS.map((period) => (
            <SelectItem key={period.value} value={period.value}>
              {period.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {loading ? (
        <TableSkeleton rows={6} columns={6} />
      ) : error ? (
        <Card>
          <CardHeader>
            <CardTitle>Usage is unavailable</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">{error}</p>
          </CardContent>
        </Card>
      ) : usage ? (
        <>
          {usage.scope === "user" && (
            <p className="text-sm text-muted-foreground">
              You see your own usage.
            </p>
          )}

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              title="Requests"
              value={usage.totals.requests.toLocaleString()}
              testId="usage-total-requests"
            />
            <StatCard
              title="Input tokens"
              value={usage.totals.prompt_tokens.toLocaleString()}
              testId="usage-total-prompt-tokens"
            />
            <StatCard
              title="Output tokens"
              value={usage.totals.completion_tokens.toLocaleString()}
              testId="usage-total-completion-tokens"
            />
            <StatCard
              title="Spend USD"
              value={formatUsd(usage.totals.spend)}
              testId="usage-total-spend"
            />
          </div>

          <Table>
            <TableCaption>By target</TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>Target</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Requests</TableHead>
                <TableHead>Tokens in</TableHead>
                <TableHead>Tokens out</TableHead>
                <TableHead>Spend</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {usage.by_target.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-muted-foreground">
                    No usage in this period.
                  </TableCell>
                </TableRow>
              ) : (
                usage.by_target.map((entry) => (
                  <TableRow key={entry.target}>
                    <TableCell>{entry.label}</TableCell>
                    <TableCell>{entry.model}</TableCell>
                    <TableCell>{entry.requests.toLocaleString()}</TableCell>
                    <TableCell>
                      {entry.prompt_tokens.toLocaleString()}
                    </TableCell>
                    <TableCell>
                      {entry.completion_tokens.toLocaleString()}
                    </TableCell>
                    <TableCell>{formatUsd(entry.spend)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>

          <Table>
            <TableCaption>By user and day</TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>Day</TableHead>
                <TableHead>User</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>Model</TableHead>
                <TableHead>Requests</TableHead>
                <TableHead>Tokens</TableHead>
                <TableHead>Spend</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {usage.rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={7} className="text-muted-foreground">
                    No usage in this period.
                  </TableCell>
                </TableRow>
              ) : (
                usage.rows.map((row) => (
                  <TableRow key={`${row.user}-${row.target}-${row.day}`}>
                    <TableCell>{row.day}</TableCell>
                    <TableCell>{row.user ?? "Unattributed"}</TableCell>
                    <TableCell>{row.label}</TableCell>
                    <TableCell>{row.model}</TableCell>
                    <TableCell>{row.requests.toLocaleString()}</TableCell>
                    <TableCell>
                      {(
                        row.prompt_tokens + row.completion_tokens
                      ).toLocaleString()}
                    </TableCell>
                    <TableCell>{formatUsd(row.spend)}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>

          {usage.capped && (
            <p className="text-sm text-muted-foreground">
              Showing a capped subset of rows; narrow the period for a complete
              count.
            </p>
          )}
        </>
      ) : null}
    </div>
  );
}
