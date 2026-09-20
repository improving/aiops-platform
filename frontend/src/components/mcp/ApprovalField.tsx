import { Label } from "@/components/ui/label";
import type { McpApproval } from "@/types/mcp";

const OPTIONS: { value: McpApproval; label: string; hint: string }[] = [
  {
    value: "never",
    label: "Never",
    hint: "Tools run at once. A member can still turn on Ask before each call.",
  },
  {
    value: "writes",
    label: "For tools that can change data",
    hint: "Every tool that does not say it only reads.",
  },
  { value: "always", label: "Always", hint: "Every tool of this server." },
];

/**
 * When Chat asks the member before a tool of the server runs. The
 * admin's floor: a member's own "Ask before each call" can only add to
 * it. It binds the chat playground, which the platform runs; an IDE or
 * SDK on the MCP endpoint decides about approval in its own client.
 */
export function ApprovalField({
  idPrefix,
  value,
  onChange,
}: {
  idPrefix: string;
  value: McpApproval;
  onChange: (value: McpApproval) => void;
}) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">Ask before a call in Chat</legend>
      {OPTIONS.map((option) => (
        <div key={option.value} className="flex items-start gap-2">
          <input
            type="radio"
            className="mt-1"
            id={`${idPrefix}-approval-${option.value}`}
            name={`${idPrefix}-approval`}
            checked={value === option.value}
            onChange={() => onChange(option.value)}
          />
          <div>
            <Label htmlFor={`${idPrefix}-approval-${option.value}`}>
              {option.label}
            </Label>
            <p className="text-xs text-muted-foreground">{option.hint}</p>
          </div>
        </div>
      ))}
    </fieldset>
  );
}
