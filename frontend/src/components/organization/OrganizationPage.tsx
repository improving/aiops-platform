"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useToast } from "@/components/hooks/use-toast";
import { TableSkeleton } from "@/components/LoadingState";
import { useOrg } from "@/hooks/useOrg";
import { parseApiError } from "@/lib/utils";
import { orgService } from "@/services/orgService";
import type {
  Invitation,
  OrganizationMember,
  OrgRole,
} from "@/types/organization";
import { CreateOrganizationDialog } from "./CreateOrganizationDialog";
import { InvitationsTable } from "./InvitationsTable";
import { InviteDialog } from "./InviteDialog";
import { MembersTable } from "./MembersTable";

// /organization (spec 5.5): summary, members with role and remove,
// invitations with invite and withdraw, and "Create organization" for
// platform admins. The budget control stays on /providers.
export default function OrganizationPage() {
  const { toast } = useToast();
  const {
    org,
    isAdmin,
    isPlatformAdmin,
    loading: orgLoading,
    refresh,
  } = useOrg();
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [loading, setLoading] = useState(true);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  const fetchAdminData = useCallback(async () => {
    try {
      const [memberRows, invitationRows] = await Promise.all([
        orgService.getMembers(),
        orgService.getInvitations(),
      ]);
      setMembers(memberRows);
      setInvitations(invitationRows);
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    if (orgLoading) return;
    (async () => {
      if (isAdmin) {
        await fetchAdminData();
      } else {
        setLoading(false);
      }
    })();
  }, [orgLoading, isAdmin, fetchAdminData]);

  const handleRoleChange = async (userId: string, role: OrgRole) => {
    try {
      const updated = await orgService.setMemberRole(userId, role);
      setMembers((prev) =>
        prev.map((m) => (m.user_id === updated.user_id ? updated : m))
      );
      // Refresh org.role too: an admin who demotes themselves must lose
      // admin-only controls right away, not after the next reload.
      await refresh();
    } catch (error) {
      toast(parseApiError(error));
    }
  };

  const handleRemove = async (userId: string) => {
    await orgService.removeMember(userId);
    setMembers((prev) => prev.filter((m) => m.user_id !== userId));
    await refresh();
  };

  const handleWithdraw = async (id: string) => {
    await orgService.withdrawInvitation(id);
    setInvitations((prev) => prev.filter((i) => i.id !== id));
  };

  if (orgLoading || loading) {
    return <TableSkeleton rows={6} columns={5} />;
  }
  if (!org) {
    return (
      <p className="text-muted-foreground">
        The organization could not be loaded.
      </p>
    );
  }

  return (
    <div className="space-y-8">
      <Card>
        <CardHeader>
          <CardTitle>{org.name}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-6 text-sm">
            <div>
              <p className="text-muted-foreground">Slug</p>
              <p className="font-mono">{org.slug}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Members</p>
              <p data-testid="member-count">{org.member_count}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Your role</p>
              <p>{org.role}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline">
              <Link href="/providers">Budget on the Providers page</Link>
            </Button>
            {isAdmin && (
              <Button onClick={() => setInviteOpen(true)}>Invite</Button>
            )}
            {isPlatformAdmin && (
              <Button variant="outline" onClick={() => setCreateOpen(true)}>
                Create organization
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {isAdmin ? (
        <>
          <MembersTable
            members={members}
            onRoleChange={handleRoleChange}
            onRemove={handleRemove}
          />
          <InvitationsTable
            invitations={invitations}
            onWithdraw={handleWithdraw}
          />
          <InviteDialog
            open={inviteOpen}
            onOpenChange={setInviteOpen}
            onInvited={(invitation) =>
              setInvitations((prev) => [
                invitation,
                ...prev.filter((i) => i.id !== invitation.id),
              ])
            }
          />
        </>
      ) : (
        <p className="text-muted-foreground">
          Only organization admins can manage members.
        </p>
      )}
      {isPlatformAdmin && (
        <CreateOrganizationDialog
          open={createOpen}
          onOpenChange={setCreateOpen}
        />
      )}
    </div>
  );
}
