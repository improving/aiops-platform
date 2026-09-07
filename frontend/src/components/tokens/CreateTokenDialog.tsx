"use client";

import { useEffect, useRef, useState } from "react";
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
import { CodeSnippet } from "@/components/CodeSnippet";
import { CopyButton } from "@/components/CopyButton";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";
import { tokenService } from "@/services/tokenService";
import type { CreatedApiToken } from "@/types/organization";

const SCOPES = [
  { value: "read", label: "Read only" },
  { value: "write", label: "Read and write" },
] as const;
// backend/auth/tokens.py: 1 to 365 days, default 90.
const EXPIRIES = [
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "365", label: "365 days" },
];

interface CreateTokenDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The active organization's slug; the token is only ever valid there. */
  orgSlug: string;
  onCreated: () => void;
}

// A token fixes its organization at creation (backend/api/tokens.py); an
// X-Org header on the request changes nothing, so the example does not
// send one. `baseUrl` is the browser's own origin plus the UI proxy path
// (window.location.origin + "/api"), not the build-time backend URL: the
// proxy is what a signed-in browser actually talks to, and it forwards a
// request's own Authorization header untouched when there is no session
// (src/proxy.ts), which is exactly the curl case.
export function curlExample(token: string, baseUrl: string): string {
  return [
    `curl ${baseUrl}/v1alpha1/inferenceInstance \\`,
    `  -H "Authorization: Bearer ${token}"`,
  ].join("\n");
}

// POST /v1alpha1/tokens. The dialog has two faces: the form, then the
// one-time reveal (spec 5.4). While the reveal is showing, or while a
// create call is in flight, Escape, an overlay click and the corner "X"
// are all suppressed (blockClose below) so the secret cannot be lost by
// accident; "Done" is the only way to dismiss it, and it wipes the token
// from state on the way out. If the dialog is closed (by the parent, or
// any other path) while the create call is still in flight, the response
// arrives to a closed dialog and openRef stops it from ever calling
// setCreated: the secret is dropped instead of being stashed unseen.
export function CreateTokenDialog({
  open,
  onOpenChange,
  orgSlug,
  onCreated,
}: CreateTokenDialogProps) {
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [scope, setScope] = useState<"read" | "write">("write");
  const [expiry, setExpiry] = useState("90");
  const [saving, setSaving] = useState(false);
  const [created, setCreated] = useState<CreatedApiToken | null>(null);
  const [curl, setCurl] = useState("");
  const openRef = useRef(open);

  useEffect(() => {
    openRef.current = open;
  }, [open]);

  // Once the token is on screen, or while a create call is in flight, the
  // only way out is "Done".
  const blockClose = created !== null || saving;

  const close = (next: boolean) => {
    if (!next) {
      setName("");
      setScope("write");
      setExpiry("90");
      setCreated(null);
      setCurl("");
    }
    onOpenChange(next);
  };

  const preventWhileBlocked = (event: { preventDefault: () => void }) => {
    if (blockClose) event.preventDefault();
  };

  const handleCreate = async () => {
    setSaving(true);
    try {
      const token = await tokenService.create({
        name: name.trim(),
        scope,
        expires_in_days: Number(expiry),
      });
      // The dialog closed while the request was in flight; drop the
      // secret instead of revealing it into a dialog nobody asked to see.
      if (!openRef.current) return;
      setCreated(token);
      setCurl(curlExample(token.token, `${window.location.origin}/api`));
      onCreated();
    } catch (error) {
      toast(parseApiError(error));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent
        showCloseButton={!blockClose}
        onEscapeKeyDown={preventWhileBlocked}
        onPointerDownOutside={preventWhileBlocked}
        onInteractOutside={preventWhileBlocked}
      >
        <DialogHeader>
          <DialogTitle>Create token</DialogTitle>
          <DialogDescription>
            {created
              ? "Copy the token now; it is not shown again."
              : "A personal token for curl, SDKs and CI, valid in this organization."}
          </DialogDescription>
        </DialogHeader>
        {created ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <code
                className="break-all rounded-md bg-muted px-2 py-1 text-xs"
                data-testid="new-token"
              >
                {created.token}
              </code>
              <CopyButton label="API token" text={created.token} />
            </div>
            <CodeSnippet label="curl example" code={curl} />
            <p className="text-xs text-muted-foreground">
              This token acts in <span className="font-medium">{orgSlug}</span>,
              the organization it was created in; it ignores any X-Org header a
              request sends.
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="token-name">Name</Label>
              <Input
                id="token-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="laptop"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="token-scope">Scope</Label>
              <Select
                value={scope}
                onValueChange={(v) => setScope(v as "read" | "write")}
              >
                <SelectTrigger id="token-scope" aria-label="Scope">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SCOPES.map((s) => (
                    <SelectItem key={s.value} value={s.value}>
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="token-expiry">Expires in</Label>
              <Select value={expiry} onValueChange={setExpiry}>
                <SelectTrigger id="token-expiry" aria-label="Expires in">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EXPIRIES.map((e) => (
                    <SelectItem key={e.value} value={e.value}>
                      {e.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        )}
        <DialogFooter>
          {created ? (
            <div className="flex w-full flex-col items-end gap-2">
              <p className="text-xs text-muted-foreground">
                This token will not be shown again.
              </p>
              <Button onClick={() => close(false)}>Done</Button>
            </div>
          ) : (
            <>
              <Button
                variant="outline"
                onClick={() => close(false)}
                disabled={saving}
              >
                Cancel
              </Button>
              <Button
                onClick={handleCreate}
                loading={saving}
                disabled={!name.trim()}
              >
                Create
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
