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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/hooks/use-toast";
import { parseApiError } from "@/lib/utils";
import { mcpService } from "@/services/mcpService";
import type { McpServer, McpTool, McpTransport } from "@/types/mcp";
import {
  CredentialFields,
  OWN_HINT,
  credentialFromFields,
} from "@/components/mcp/CredentialFields";
import { ToolPicker } from "@/components/mcp/ToolPicker";

// backend/api/mcp.py: lower case letters, digits and "_", starting with a
// letter, 32 characters at most.
const NAME_RE = /^[a-z][a-z0-9_]{0,30}[a-z0-9]$|^[a-z]$/;

interface AddMcpServerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (server: McpServer) => void;
  /** Prefills the connection step from a "Try one" link (W1). */
  initial?: { name: string; url: string };
}

export function AddMcpServerDialog({
  open,
  onOpenChange,
  onCreated,
  initial,
}: AddMcpServerDialogProps) {
  const { toast } = useToast();
  const [step, setStep] = useState<1 | 2>(1);
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState("");
  const [url, setUrl] = useState(initial?.url ?? "");
  const [transport, setTransport] = useState<McpTransport>("http");
  const [authType, setAuthType] = useState("none");
  const [token, setToken] = useState("");
  const [headerName, setHeaderName] = useState("");
  const [headerValue, setHeaderValue] = useState("");
  const [perUser, setPerUser] = useState(false);
  const [helpUrl, setHelpUrl] = useState("");
  const [tools, setTools] = useState<McpTool[]>([]);
  const [allowAll, setAllowAll] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A new "Try one" link re-fills the form while the dialog is already
  // mounted (it is rendered once by the page, not per link).
  useEffect(() => {
    if (open && initial) {
      setName(initial.name);
      setUrl(initial.url);
    }
    // Only on open: typing in the form afterwards must not be overwritten,
    // so `initial` is deliberately not a dependency here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const reset = () => {
    setStep(1);
    setName("");
    setDescription("");
    setUrl("");
    setTransport("http");
    setAuthType("none");
    setToken("");
    setHeaderName("");
    setHeaderValue("");
    setPerUser(false);
    setHelpUrl("");
    setTools([]);
    setAllowAll(true);
    setSelected(new Set());
    setError(null);
  };

  const close = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const ownCredentials = authType !== "none" && perUser;
  const nameValid = NAME_RE.test(name);
  const credentialComplete =
    authType !== "bearer" && authType !== "header"
      ? true
      : authType === "bearer"
        ? token.trim() !== ""
        : headerName.trim() !== "" && headerValue.trim() !== "";
  const canTest =
    nameValid && url.trim() !== "" && credentialComplete && !testing;

  const handleTest = async () => {
    setError(null);
    setTesting(true);
    try {
      const discovered = await mcpService.discover({
        url: url.trim(),
        transport,
        credential: credentialFromFields(
          authType,
          token,
          headerName,
          headerValue
        ),
      });
      setTools(discovered);
      setAllowAll(true);
      setSelected(new Set(discovered.map((t) => t.name)));
      setStep(2);
    } catch (err) {
      setError(parseApiError(err).description as string);
    } finally {
      setTesting(false);
    }
  };

  const toggleTool = (toolName: string, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(toolName);
      else next.delete(toolName);
      return next;
    });
  };

  const handleAdd = async () => {
    setError(null);
    setSaving(true);
    try {
      const server = await mcpService.createServer({
        name,
        url: url.trim(),
        transport,
        description: description.trim() || undefined,
        credential: credentialFromFields(
          authType,
          token,
          headerName,
          headerValue
        ),
        allowed_tools: allowAll ? null : Array.from(selected),
        ...(ownCredentials
          ? {
              credential_mode: "per_user" as const,
              credential_help_url: helpUrl.trim() || undefined,
            }
          : {}),
      });
      toast({
        title: "Success",
        description: "MCP server added",
        variant: "success",
      });
      onCreated(server);
      reset();
    } catch (err) {
      setError(parseApiError(err).description as string);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add MCP server</DialogTitle>
          <DialogDescription>
            {step === 1 ? "Step 1 of 2: Connection" : "Step 2 of 2: Tools"}
          </DialogDescription>
        </DialogHeader>

        {step === 1 ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="mcp-name">Name</Label>
              <Input
                id="mcp-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="github"
              />
              {name.trim() !== "" && !nameValid && (
                <p className="text-xs text-destructive">
                  Lower case letters, digits and _; starts with a letter.
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="mcp-description">Description</Label>
              <Input
                id="mcp-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="mcp-url">Server URL</Label>
              <Input
                id="mcp-url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://api.example.com/mcp/"
              />
            </div>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Transport</legend>
              <div className="flex flex-wrap gap-4">
                <div className="flex items-center gap-2">
                  <input
                    type="radio"
                    id="mcp-transport-http"
                    name="mcp-transport"
                    checked={transport === "http"}
                    onChange={() => setTransport("http")}
                    className="h-4 w-4"
                  />
                  <Label htmlFor="mcp-transport-http">Streamable HTTP</Label>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="radio"
                    id="mcp-transport-sse"
                    name="mcp-transport"
                    checked={transport === "sse"}
                    onChange={() => setTransport("sse")}
                    className="h-4 w-4"
                  />
                  <Label htmlFor="mcp-transport-sse">SSE (legacy)</Label>
                </div>
              </div>
            </fieldset>

            <CredentialFields
              idPrefix="mcp-add"
              hint={perUser ? OWN_HINT : undefined}
              authType={authType}
              onAuthTypeChange={setAuthType}
              token={token}
              onTokenChange={setToken}
              headerName={headerName}
              onHeaderNameChange={setHeaderName}
              headerValue={headerValue}
              onHeaderValueChange={setHeaderValue}
            />
            {authType !== "none" && (
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium">Credential</legend>
                <div className="flex items-center gap-2">
                  <input
                    type="radio"
                    id="mcp-add-cred-shared"
                    name="mcp-add-cred-mode"
                    checked={!perUser}
                    onChange={() => setPerUser(false)}
                  />
                  <Label htmlFor="mcp-add-cred-shared">
                    One shared credential
                  </Label>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="radio"
                    id="mcp-add-cred-own"
                    name="mcp-add-cred-mode"
                    checked={perUser}
                    onChange={() => setPerUser(true)}
                  />
                  <Label htmlFor="mcp-add-cred-own">
                    Each member brings their own
                  </Label>
                </div>
                {perUser && (
                  <>
                    <p className="text-xs text-muted-foreground">
                      The value above is yours: it tests the connection and
                      stays your own credential. Every other member connects
                      theirs, and the model then does what their credential can
                      do.
                    </p>
                    <div className="space-y-1">
                      <Label htmlFor="mcp-add-help-url">
                        Where to get a credential
                      </Label>
                      <Input
                        id="mcp-add-help-url"
                        value={helpUrl}
                        onChange={(e) => setHelpUrl(e.target.value)}
                        placeholder="https://github.com/settings/tokens"
                      />
                    </div>
                  </>
                )}
              </fieldset>
            )}

            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-sm font-medium text-green-700 dark:text-green-500">
              Connected · {tools.length} tools found
            </p>
            <ToolPicker
              idPrefix="mcp-add"
              tools={tools}
              allowAll={allowAll}
              onAllowAllChange={setAllowAll}
              selected={selected}
              onToggle={toggleTool}
            />
            <p className="text-xs text-muted-foreground">
              {ownCredentials
                ? "Each member's models call these tools with that member's own credential."
                : authType === "none"
                  ? "Members' models call these tools; the server asks for no credential."
                  : "Members' models call these tools with the shared credential above."}
            </p>
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
          </div>
        )}

        <DialogFooter>
          {step === 1 ? (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={() => close(false)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                onClick={handleTest}
                disabled={!canTest}
                loading={testing}
              >
                Test connection
              </Button>
            </>
          ) : (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setError(null);
                  setStep(1);
                }}
                disabled={saving}
              >
                Back
              </Button>
              <Button type="button" onClick={handleAdd} loading={saving}>
                Add server
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
