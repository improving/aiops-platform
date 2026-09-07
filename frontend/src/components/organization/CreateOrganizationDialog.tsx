"use client";

import { useState } from "react";
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
import { useToast } from "@/components/hooks/use-toast";
import { setOrgCookie } from "@/lib/orgCookie";
import { parseApiError } from "@/lib/utils";
import { orgService } from "@/services/orgService";

// Mirrors backend/api/organizations.py SLUG_RULE.
const SLUG_RULE = /^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$/;

interface CreateOrganizationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// POST /v1alpha1/organizations (platform admins). The creator becomes its
// admin; the page switches to it by setting the cookie and reloading.
export function CreateOrganizationDialog({
  open,
  onOpenChange,
}: CreateOrganizationDialogProps) {
  const { toast } = useToast();
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  const valid = SLUG_RULE.test(slug) && name.trim().length > 0;

  const handleCreate = async () => {
    setSaving(true);
    try {
      const created = await orgService.create({ slug, name: name.trim() });
      setOrgCookie(created.slug);
      window.location.reload();
    } catch (error) {
      toast(parseApiError(error));
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create organization</DialogTitle>
          <DialogDescription>
            You become its first admin and switch to it right away.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="org-slug">Slug</Label>
            <Input
              id="org-slug"
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase())}
              placeholder="acme"
            />
            <p className="text-xs text-muted-foreground">
              Lowercase letters, digits and dashes; 3 to 40 characters.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="org-name">Name</Label>
            <Input
              id="org-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Acme Corp"
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button onClick={handleCreate} loading={saving} disabled={!valid}>
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
