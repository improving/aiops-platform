"use client";

import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";
import { mcpService } from "@/services/mcpService";
import type { McpServer } from "@/types/mcp";
import {
  CredentialFields,
  credentialFromFields,
} from "@/components/mcp/CredentialFields";

/** "Change credential" (W4/W5): the same Authentication fields as step 1
    of Add, plus "Remove credential" when the server currently has one. */
export function ChangeCredentialDialog({
  server,
  open,
  onOpenChange,
  onUpdated,
}: {
  server: McpServer | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (server: McpServer) => void;
}) {
  const { toast } = useToast();
  const [authType, setAuthType] = useState("none");
  const [token, setToken] = useState("");
  const [headerName, setHeaderName] = useState("");
  const [headerValue, setHeaderValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A server where each member has their own: this dialog replaces them
  // all with one (or none), so the admin says so first.
  const replacesMembers = server?.credential_mode === "per_user";
  const [confirmed, setConfirmed] = useState(false);

  useEffect(() => {
    if (open) {
      setConfirmed(false);
      setAuthType("none");
      setToken("");
      setHeaderName("");
      setHeaderValue("");
      setError(null);
    }
  }, [open]);

  const canSave =
    (!replacesMembers || confirmed) &&
    (authType === "remove" ||
      (authType === "bearer" && token.trim() !== "") ||
      (authType === "header" &&
        headerName.trim() !== "" &&
        headerValue.trim() !== ""));

  const handleSave = async () => {
    if (!server) return;
    setError(null);
    setSaving(true);
    try {
      const updated = await mcpService.updateServer(
        server.id,
        authType === "remove"
          ? { remove_credential: true, credential_mode: "none" }
          : {
              credential_mode: "shared",
              credential: credentialFromFields(
                authType,
                token,
                headerName,
                headerValue
              ),
            }
      );
      toast({
        title: "Success",
        description: "Credential updated",
        variant: "success",
      });
      onUpdated(updated);
      onOpenChange(false);
    } catch (err) {
      setError(parseApiError(err).description as string);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Change credential</DialogTitle>
          <DialogDescription>
            {server ? `The credential ${server.name} connects with.` : ""}
          </DialogDescription>
        </DialogHeader>
        {replacesMembers && (
          <div
            role="alert"
            className="space-y-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm"
          >
            <p>
              Each member has their own credential on this server. One shared
              credential (or none) replaces them: every member&apos;s credential
              is deleted. To change only yours, use &quot;Replace my
              credential&quot;.
            </p>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="mcp-cred-confirm"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              <Label htmlFor="mcp-cred-confirm">
                Delete every member&apos;s credential
              </Label>
            </div>
          </div>
        )}
        <CredentialFields
          idPrefix="mcp-credential"
          authType={authType}
          onAuthTypeChange={setAuthType}
          token={token}
          onTokenChange={setToken}
          headerName={headerName}
          onHeaderNameChange={setHeaderName}
          headerValue={headerValue}
          onHeaderValueChange={setHeaderValue}
          extraOptions={
            server?.credential_mode === "shared"
              ? [{ value: "remove", label: "Remove credential" }]
              : []
          }
        />
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleSave}
            disabled={!canSave}
            loading={saving}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
