"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { McpCredentialInput } from "@/types/mcp";

/** The three ways a caller states how the server should be reached, plus
    any options a dialog appends to the same radio group (`ChangeCredentialDialog`
    adds "Remove credential"). */
export type AuthType = "none" | "bearer" | "header";

/** Builds the payload `mcpService` expects; "none" (or an unknown extra
    value, e.g. "remove") carries no credential. */
export function credentialFromFields(
  authType: string,
  token: string,
  headerName: string,
  headerValue: string
): McpCredentialInput | undefined {
  if (authType === "bearer") return { auth_type: "bearer", value: token };
  if (authType === "header") {
    return { auth_type: "header", auth_header: headerName, value: headerValue };
  }
  return undefined;
}

/**
 * The Authentication radio group and its follow-up fields, shared by
 * `AddMcpServerDialog` (step 1) and `ChangeCredentialDialog`. `idPrefix`
 * keeps radio `name`/input `id` unique when more than one instance could
 * ever be mounted at once.
 */
const SHARED_HINT = "Stored as a Kubernetes Secret. Shared by every member.";
export const OWN_HINT =
  "Stored as a Kubernetes Secret. Only your requests use it.";

export function CredentialFields({
  idPrefix,
  hint = SHARED_HINT,
  authType,
  onAuthTypeChange,
  token,
  onTokenChange,
  headerName,
  onHeaderNameChange,
  headerValue,
  onHeaderValueChange,
  extraOptions = [],
}: {
  idPrefix: string;
  /** Under the value: who uses it. The default is for one credential
      of the organization. */
  hint?: string;
  authType: string;
  onAuthTypeChange: (value: string) => void;
  token: string;
  onTokenChange: (value: string) => void;
  headerName: string;
  onHeaderNameChange: (value: string) => void;
  headerValue: string;
  onHeaderValueChange: (value: string) => void;
  /** Extra radio choices appended after "Custom header", e.g. "Remove
      credential". Neither the token nor the header fields render for one
      of these. */
  extraOptions?: { value: string; label: string }[];
}) {
  const options: { value: AuthType | string; label: string }[] = [
    { value: "none", label: "None" },
    { value: "bearer", label: "Bearer token" },
    { value: "header", label: "Custom header" },
    ...extraOptions,
  ];

  return (
    <div className="space-y-3">
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Authentication</legend>
        <div className="flex flex-wrap gap-4">
          {options.map((option) => (
            <div key={option.value} className="flex items-center gap-2">
              <input
                type="radio"
                id={`${idPrefix}-auth-${option.value}`}
                name={`${idPrefix}-auth-type`}
                value={option.value}
                checked={authType === option.value}
                onChange={() => onAuthTypeChange(option.value)}
                className="h-4 w-4"
              />
              <Label htmlFor={`${idPrefix}-auth-${option.value}`}>
                {option.label}
              </Label>
            </div>
          ))}
        </div>
      </fieldset>

      {authType === "bearer" && (
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-token`}>Token</Label>
          <Input
            id={`${idPrefix}-token`}
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => onTokenChange(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">{hint}</p>
        </div>
      )}

      {authType === "header" && (
        <div className="space-y-2">
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-header-name`}>Header name</Label>
            <Input
              id={`${idPrefix}-header-name`}
              value={headerName}
              onChange={(e) => onHeaderNameChange(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-header-value`}>Header value</Label>
            <Input
              id={`${idPrefix}-header-value`}
              type="password"
              autoComplete="off"
              value={headerValue}
              onChange={(e) => onHeaderValueChange(e.target.value)}
            />
          </div>
          <p className="text-xs text-muted-foreground">{hint}</p>
        </div>
      )}
    </div>
  );
}
