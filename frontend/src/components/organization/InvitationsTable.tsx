"use client";

import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CopyButton } from "@/components/CopyButton";
import { DeleteButton } from "@/components/DeleteButton";
import {
  applyListControls,
  ListControls,
  ShowMore,
  useListState,
} from "@/components/ListControls";
import type { Invitation } from "@/types/organization";

interface InvitationsTableProps {
  invitations: Invitation[];
  onWithdraw: (id: string) => Promise<void>;
}

// "Ready" in the shared status filter means accepted; pending invitations
// are "Not ready". The sign-in URL is the app's own /login: no email is
// sent, the admin passes the link on (spec 5.2).
export function InvitationsTable({
  invitations,
  onWithdraw,
}: InvitationsTableProps) {
  const [state, update, nextPage] = useListState();
  // No fetch involved, so no mount effect: window exists once this client
  // component renders in the browser, and the value never appears in the
  // DOM (only as a CopyButton clipboard payload), so there is nothing for
  // an SSR/hydration mismatch to catch.
  const signInUrl =
    typeof window !== "undefined" ? `${window.location.origin}/login` : "";

  const { visible, total, hasMore } = applyListControls(invitations, state, {
    name: (i) => i.email,
    ready: (i) => i.accepted_at !== null,
  });

  return (
    <div className="space-y-4">
      <ListControls state={state} onChange={update} />
      <Table>
        <TableCaption>Invitations</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>Email</TableHead>
            <TableHead>Role</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Created</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {visible.length === 0 ? (
            <TableRow>
              <TableCell colSpan={5} className="text-muted-foreground">
                No invitations.
              </TableCell>
            </TableRow>
          ) : (
            visible.map((invitation) => (
              <TableRow key={invitation.id}>
                <TableCell className="font-medium">
                  {invitation.email}
                </TableCell>
                <TableCell>{invitation.role}</TableCell>
                <TableCell>
                  {invitation.accepted_at ? "Accepted" : "Pending"}
                </TableCell>
                <TableCell>
                  {new Date(invitation.created_at).toLocaleDateString()}
                </TableCell>
                <TableCell>
                  {invitation.accepted_at === null && (
                    <div className="flex gap-2">
                      <CopyButton label="sign-in URL" text={signInUrl} />
                      <DeleteButton
                        buttonText="Withdraw"
                        modalTitle="Withdraw invitation"
                        modalDescription={`Withdraw the invitation for ${invitation.email}?`}
                        successToastMessage="Invitation withdrawn"
                        onDelete={() => onWithdraw(invitation.id)}
                      />
                    </div>
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
    </div>
  );
}
