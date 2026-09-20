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
import { parseApiError } from "@/lib/utils";
import { mcpService } from "@/services/mcpService";
import type { McpServer } from "@/types/mcp";

/**
 * A member's own credential for a server where each member brings
 * theirs. The backend tries the value against the server before it
 * stores it, so a refusal shows here, in place, and nothing is saved.
 * The value is never shown again: replacing it is typing a new one.
 */
export function ConnectCredentialDialog({
  server,
  onOpenChange,
  onSaved,
}: {
  /** null closes the dialog. */
  server: McpServer | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (server: McpServer) => void;
}) {
  const { toast } = useToast();
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const close = (open: boolean) => {
    if (!open) {
      setValue("");
      setError(null);
    }
    onOpenChange(open);
  };

  const save = async () => {
    if (!server) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await mcpService.setOwnCredential(
        server.id,
        value.trim()
      );
      toast({
        title: "Success",
        description: `Connected to ${server.name}`,
        variant: "success",
      });
      onSaved(updated);
      close(false);
    } catch (e) {
      setError(String(parseApiError(e).description));
    } finally {
      setSaving(false);
    }
  };

  const bearer =
    (server?.credential_header ?? "Authorization") === "Authorization";
  const label = bearer ? "Personal access token" : server?.credential_header;
  return (
    <Dialog open={server !== null} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Connect {server?.name}</DialogTitle>
          <DialogDescription>
            This server uses your own credential. The model can then do what
            your credential can do.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="mcp-own-credential">{label}</Label>
          <Input
            id="mcp-own-credential"
            type="password"
            autoComplete="off"
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          {server?.credential_help_url && (
            <a
              href={server.credential_help_url}
              target="_blank"
              rel="noreferrer"
              className="block text-xs underline"
            >
              Where to get one
            </a>
          )}
          <p className="text-xs text-muted-foreground">
            Stored as a Kubernetes Secret. Only your requests use it, and you
            can remove it at any time.
          </p>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => close(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={save}
            disabled={value.trim() === "" || saving}
            loading={saving}
          >
            Test and save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
