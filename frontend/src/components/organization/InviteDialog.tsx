"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";
import { orgService } from "@/services/orgService";
import { ROLES, type Invitation, type OrgRole } from "@/types/organization";

const EMAIL_RULE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

interface InviteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onInvited: (invitation: Invitation) => void;
}

// POST /v1alpha1/organizations/current/invitations: no email is sent; the
// admin copies the sign-in URL from the invitations table.
export function InviteDialog({
  open,
  onOpenChange,
  onInvited,
}: InviteDialogProps) {
  const { toast } = useToast();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<OrgRole>("member");
  const [saving, setSaving] = useState(false);
  const [emailInvalid, setEmailInvalid] = useState(false);

  const close = (next: boolean) => {
    if (!next) {
      setEmail("");
      setRole("member");
      setEmailInvalid(false);
    }
    onOpenChange(next);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = email.trim();
    if (!EMAIL_RULE.test(trimmed)) {
      setEmailInvalid(true);
      return;
    }
    setSaving(true);
    try {
      const invitation = await orgService.invite({ email: trimmed, role });
      toast({
        title: "Invitation created",
        description: `${invitation.email} can sign in and will join as ${invitation.role}.`,
        variant: "success",
      });
      onInvited(invitation);
      close(false);
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Invite a member</DialogTitle>
          <DialogDescription>
            The person joins this organization with the role below the next time
            they sign in with this email.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="invite-email">Email</Label>
              <Input
                id="invite-email"
                type="email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (emailInvalid) setEmailInvalid(false);
                }}
                placeholder="person@example.com"
                aria-invalid={emailInvalid}
                aria-describedby={
                  emailInvalid ? "invite-email-error" : undefined
                }
              />
              {emailInvalid && (
                <p id="invite-email-error" className="text-sm text-destructive">
                  Enter a valid email address
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="invite-role">Role</Label>
              <Select value={role} onValueChange={(v) => setRole(v as OrgRole)}>
                <SelectTrigger id="invite-role" aria-label="Role">
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
            </div>
          </div>
          <DialogFooter className="mt-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => close(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button type="submit" loading={saving} disabled={!email.trim()}>
              Send invitation
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
