"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DeleteButton } from "@/components/DeleteButton";
import { useToast } from "@/components/hooks/use-toast";
import {
  applyListControls,
  ListControls,
  ShowMore,
  useListState,
} from "@/components/ListControls";
import { TableSkeleton } from "@/components/LoadingState";
import { useOrg } from "@/hooks/useOrg";
import { formatDate, parseApiError } from "@/lib/utils";
import { tokenService } from "@/services/tokenService";
import type { ApiToken } from "@/types/organization";
import { CreateTokenDialog } from "./CreateTokenDialog";

const DAY_MS = 24 * 60 * 60 * 1000;
const SOON_DAYS = 7;

export function tokenStatus(token: ApiToken, now: number): string {
  if (token.revoked_at) return "Revoked";
  const remaining = Date.parse(token.expires_at) - now;
  if (remaining <= 0) return "Expired";
  const days = Math.ceil(remaining / DAY_MS);
  if (days <= SOON_DAYS)
    return `Expires in ${days} day${days === 1 ? "" : "s"}`;
  return "Active";
}

export function isActive(token: ApiToken, now: number): boolean {
  return !token.revoked_at && Date.parse(token.expires_at) > now;
}

// /settings/tokens (spec 5.4). `now` is taken when the list is fetched,
// never during render (React Compiler purity rule).
export default function TokensPage() {
  const { toast } = useToast();
  const { org, isAdmin, loading: orgLoading } = useOrg();
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [now, setNow] = useState(0);
  const [all, setAll] = useState(false);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [state, update, nextPage] = useListState();

  const fetchTokens = useCallback(
    async (everyone: boolean) => {
      try {
        setTokens(await tokenService.list(everyone));
        setNow(Date.now());
      } catch (error) {
        toast(parseApiError(error));
      } finally {
        setLoading(false);
      }
    },
    [toast]
  );

  useEffect(() => {
    (async () => {
      await fetchTokens(all);
    })();
  }, [all, fetchTokens]);

  const handleRevoke = async (id: string) => {
    await tokenService.revoke(id);
    await fetchTokens(all);
  };

  const { visible, total, hasMore } = applyListControls(tokens, state, {
    name: (t) => t.name,
    ready: (t) => isActive(t, now),
  });

  if (orgLoading || loading) {
    return <TableSkeleton rows={5} columns={8} />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <ListControls state={state} onChange={update} />
        <div className="flex items-center gap-4">
          {isAdmin && (
            <div className="flex items-center gap-2">
              <Switch
                id="all-tokens"
                checked={all}
                onCheckedChange={(checked) => {
                  setAll(checked);
                  update({ page: 1 });
                }}
              />
              <Label htmlFor="all-tokens">
                Show every token in the organization
              </Label>
            </div>
          )}
          <Button onClick={() => setCreateOpen(true)}>Create token</Button>
        </div>
      </div>

      <Table>
        <TableCaption>API tokens</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Token</TableHead>
            <TableHead>Scope</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Created</TableHead>
            <TableHead>Expires</TableHead>
            <TableHead>Last used</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {visible.length === 0 ? (
            <TableRow>
              <TableCell colSpan={8} className="text-muted-foreground">
                No tokens yet. Create one to call the API from curl or an SDK.
              </TableCell>
            </TableRow>
          ) : (
            visible.map((token) => (
              <TableRow key={token.id}>
                <TableCell className="font-medium">{token.name}</TableCell>
                <TableCell className="font-mono text-xs">
                  aiops_{token.prefix}_…
                </TableCell>
                <TableCell>{token.scope}</TableCell>
                <TableCell>{tokenStatus(token, now)}</TableCell>
                <TableCell>{formatDate(token.created_at)}</TableCell>
                <TableCell>{formatDate(token.expires_at)}</TableCell>
                <TableCell>{formatDate(token.last_used_at)}</TableCell>
                <TableCell>
                  {isActive(token, now) && (
                    <DeleteButton
                      buttonText="Revoke"
                      modalDescription={`Revoke "${token.name}"? Calls with it answer 401 from now on.`}
                      successToastMessage="Token revoked"
                      onDelete={() => handleRevoke(token.id)}
                    />
                  )}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      <ShowMore
        hasMore={hasMore}
        onClick={nextPage}
        shown={visible.length}
        total={total}
      />

      <CreateTokenDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        orgSlug={org?.slug ?? "default"}
        onCreated={() => {
          (async () => {
            await fetchTokens(all);
          })();
        }}
      />
    </div>
  );
}
