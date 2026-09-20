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
import type {
  McpRegistryPreview,
  McpScope,
  McpServer,
  McpTool,
  McpTransport,
} from "@/types/mcp";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RegistrySearch } from "@/components/mcp/RegistrySearch";
import { useRuntimeConfig } from "@/lib/runtimeConfig";
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
  /** What this user may add, the default first: an admin
      ["organization", "personal", ...], a member ["personal"]. */
  scopes: McpScope[];
}

const SCOPE_LABEL: Record<McpScope, string> = {
  organization: "Every member of this organization",
  personal: "Only me",
  platform: "Every organization of the platform",
};

export function AddMcpServerDialog({
  open,
  onOpenChange,
  onCreated,
  initial,
  scopes,
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
  const [scope, setScope] = useState<McpScope>(scopes[0] ?? "personal");
  const [perUser, setPerUser] = useState(false);
  const [helpUrl, setHelpUrl] = useState("");
  // OAuth: each member signs in. Empty is enough when the server's
  // authorization server registers clients by itself.
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [oauthScopes, setOauthScopes] = useState("");
  const [tools, setTools] = useState<McpTool[]>([]);
  const [allowAll, setAllowAll] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // "url" is the form; "registry" is the search that fills it.
  const [tab, setTab] = useState("url");
  // After a test that the server refused: it offers an OAuth sign-in.
  const [oauthHint, setOauthHint] = useState(false);
  const { mcpRegistry } = useRuntimeConfig();

  // A new "Try one" link re-fills the form while the dialog is already
  // mounted (it is rendered once by the page, not per link).
  useEffect(() => {
    // What the user may add is known once the organization has loaded,
    // which can be after the first render: take the default on open.
    if (open) setScope(scopes[0] ?? "personal");
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
    setScope(scopes[0] ?? "personal");
    setHelpUrl("");
    setClientId("");
    setClientSecret("");
    setOauthScopes("");
    setTools([]);
    setAllowAll(true);
    setSelected(new Set());
    setError(null);
    setTab("url");
    setOauthHint(false);
  };

  // "Use" of a registry entry. It fills the form and nothing more: the
  // URL rule and the connection test are the next step, as always.
  const applyEntry = (entry: McpRegistryPreview) => {
    if (!entry.remote) return;
    setName(entry.suggested_name);
    setDescription((entry.description ?? "").slice(0, 200));
    setUrl(entry.remote.url);
    setTransport(entry.remote.transport);
    setAuthType(entry.remote.auth_type);
    setHeaderName(entry.remote.auth_header ?? "");
    setToken("");
    setHeaderValue("");
    setError(null);
    setOauthHint(false);
    setTab("url");
  };

  const close = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const bySignIn = authType === "oauth";
  const ownCredentials = authType !== "none" && !bySignIn && perUser;
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
    setOauthHint(false);
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
      const message = parseApiError(err).description as string;
      setError(message);
      // A refusal can mean "sign in": ask once whether the server
      // offers OAuth, and offer that option next to the error.
      if (/\b401\b|unauthori[sz]ed/i.test(message))
        setOauthHint(await mcpService.offersOAuth(url.trim()));
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
        credential: bySignIn
          ? undefined
          : credentialFromFields(authType, token, headerName, headerValue),
        // Nobody has a token yet, so there was no tool list to pick from.
        allowed_tools: bySignIn || allowAll ? null : Array.from(selected),
        scope,
        ...(bySignIn
          ? {
              oauth: {
                client_id: clientId.trim() || undefined,
                client_secret: clientSecret.trim() || undefined,
                scopes: oauthScopes.split(/[\s,]+/).filter(Boolean),
              },
            }
          : {}),
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
      <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Add MCP server</DialogTitle>
          <DialogDescription>
            {step === 1 ? "Step 1 of 2: Connection" : "Step 2 of 2: Tools"}
          </DialogDescription>
        </DialogHeader>

        {step === 1 ? (
          <Tabs value={tab} onValueChange={setTab} className="w-full min-w-0">
            {mcpRegistry && (
              <TabsList>
                <TabsTrigger value="url">Enter a URL</TabsTrigger>
                <TabsTrigger value="registry">
                  From the MCP registry
                </TabsTrigger>
              </TabsList>
            )}
            <TabsContent value="registry">
              <RegistrySearch onUse={applyEntry} />
            </TabsContent>
            <TabsContent value="url">
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
                      <Label htmlFor="mcp-transport-http">
                        Streamable HTTP
                      </Label>
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

                {scopes.length > 1 && (
                  <fieldset className="space-y-2">
                    <legend className="text-sm font-medium">
                      Who can use it
                    </legend>
                    {scopes.map((value) => (
                      <div key={value} className="flex items-center gap-2">
                        <input
                          type="radio"
                          id={`mcp-add-scope-${value}`}
                          name="mcp-add-scope"
                          checked={scope === value}
                          onChange={() => setScope(value)}
                        />
                        <Label htmlFor={`mcp-add-scope-${value}`}>
                          {SCOPE_LABEL[value]}
                        </Label>
                      </div>
                    ))}
                  </fieldset>
                )}
                {scopes.length === 1 && scope === "personal" && (
                  <p className="text-xs text-muted-foreground">
                    Only you can use this server. An organization admin adds
                    servers for everyone.
                  </p>
                )}

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
                  extraOptions={[
                    { value: "oauth", label: "OAuth: each member signs in" },
                  ]}
                />
                {bySignIn && (
                  <div className="space-y-3">
                    <p className="text-xs text-muted-foreground">
                      Each member signs in at the server and the platform keeps
                      their token. There is no connection test now: the tools
                      are listed when the first member has signed in. Leave the
                      client empty when the server registers clients by itself;
                      else create an OAuth application there.
                    </p>
                    <div className="space-y-1">
                      <Label htmlFor="mcp-add-client-id">
                        Client ID (optional)
                      </Label>
                      <Input
                        id="mcp-add-client-id"
                        value={clientId}
                        onChange={(e) => setClientId(e.target.value)}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="mcp-add-client-secret">
                        Client secret (optional)
                      </Label>
                      <Input
                        id="mcp-add-client-secret"
                        type="password"
                        autoComplete="off"
                        value={clientSecret}
                        onChange={(e) => setClientSecret(e.target.value)}
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="mcp-add-scopes">Scopes (optional)</Label>
                      <Input
                        id="mcp-add-scopes"
                        value={oauthScopes}
                        onChange={(e) => setOauthScopes(e.target.value)}
                        placeholder="read write"
                      />
                    </div>
                  </div>
                )}
                {authType !== "none" && !bySignIn && scope === "personal" && (
                  <p className="text-xs text-muted-foreground">
                    The credential is your own: only your requests carry it.
                  </p>
                )}
                {authType !== "none" && !bySignIn && scope !== "personal" && (
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
                          theirs, and the model then does what their credential
                          can do.
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
                {oauthHint && !bySignIn && (
                  <p className="text-sm">
                    This server offers OAuth sign-in.{" "}
                    <button
                      type="button"
                      className="font-medium underline"
                      onClick={() => {
                        setAuthType("oauth");
                        setError(null);
                        setOauthHint(false);
                      }}
                    >
                      Use OAuth sign-in
                    </button>
                  </p>
                )}
              </div>
            </TabsContent>
          </Tabs>
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
              {scope === "personal"
                ? "Your models call these tools; nobody else sees this server."
                : ownCredentials
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
              {tab === "registry" ? null : bySignIn ? (
                <Button
                  type="button"
                  onClick={handleAdd}
                  disabled={!nameValid || url.trim() === "" || saving}
                  loading={saving}
                >
                  Add server
                </Button>
              ) : (
                <Button
                  type="button"
                  onClick={handleTest}
                  disabled={!canTest}
                  loading={testing}
                >
                  Test connection
                </Button>
              )}
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
