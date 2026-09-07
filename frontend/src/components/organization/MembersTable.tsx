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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DeleteButton } from "@/components/DeleteButton";
import {
  applyListControls,
  ListControls,
  ShowMore,
  useListState,
} from "@/components/ListControls";
import {
  ROLES,
  type OrganizationMember,
  type OrgRole,
} from "@/types/organization";
import { formatDate } from "@/lib/utils";

interface MembersTableProps {
  members: OrganizationMember[];
  onRoleChange: (userId: string, role: OrgRole) => Promise<void>;
  onRemove: (userId: string) => Promise<void>;
}

function label(member: OrganizationMember): string {
  return member.email ?? member.name ?? member.user_id;
}

// Members have no readiness concept, so the Status filter does not apply
// here; the sort by name orders by email.
export function MembersTable({
  members,
  onRoleChange,
  onRemove,
}: MembersTableProps) {
  const [state, update, nextPage] = useListState();
  const { visible, total, hasMore } = applyListControls(members, state, {
    name: label,
  });

  return (
    <div className="space-y-4">
      <ListControls state={state} onChange={update} showStatusFilter={false} />
      <Table>
        <TableCaption>Members</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>Email</TableHead>
            <TableHead>Name</TableHead>
            <TableHead>Role</TableHead>
            <TableHead>Joined</TableHead>
            <TableHead>Last seen</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {visible.length === 0 ? (
            <TableRow>
              <TableCell colSpan={6} className="text-muted-foreground">
                No members.
              </TableCell>
            </TableRow>
          ) : (
            visible.map((member) => (
              <TableRow key={member.user_id}>
                <TableCell className="font-medium">
                  {member.email ?? "—"}
                </TableCell>
                <TableCell>{member.name ?? "—"}</TableCell>
                <TableCell>
                  <Select
                    value={member.role}
                    onValueChange={(v) =>
                      onRoleChange(member.user_id, v as OrgRole)
                    }
                  >
                    <SelectTrigger
                      className="w-[130px]"
                      aria-label={`Role for ${label(member)}`}
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ROLES.map((r) => (
                        <SelectItem key={r} value={r}>
                          {r}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell>{formatDate(member.created_at)}</TableCell>
                <TableCell>{formatDate(member.last_seen_at)}</TableCell>
                <TableCell>
                  <DeleteButton
                    buttonText="Remove"
                    modalTitle="Remove member"
                    modalDescription={`Remove ${label(member)} from this organization?`}
                    successToastMessage="Member removed"
                    onDelete={() => onRemove(member.user_id)}
                  />
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
