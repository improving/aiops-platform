import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  guessToolParser,
  hasToolCalling,
  withToolCalling,
  type SettingRow,
} from "@/lib/instanceSettings";

/**
 * vLLM answers 400 to a request with tools unless it started with two
 * arguments nobody guesses. The switch adds and removes them as ordinary
 * rows, with the parser of the model's family, so what is sent stays
 * visible and the parser stays editable.
 */
export function ToolCallingSwitch({
  rows,
  onChange,
  modelReference,
}: {
  rows: SettingRow[];
  onChange: (rows: SettingRow[]) => void;
  modelReference: string;
}) {
  const parser = guessToolParser(modelReference);
  return (
    <div className="mb-4 flex items-start justify-between gap-4 rounded-md border p-3">
      <div className="space-y-1">
        <Label htmlFor="tool-calling">Tool calling</Label>
        <p className="text-sm text-muted-foreground">
          Langflow agents, function calling and the tools of MCP servers in Chat
          need it. Adds <code>--enable-auto-tool-choice</code> and{" "}
          <code>--tool-call-parser {parser}</code>, the parser for this model
          family. Not every model writes tool calls the parser can read: a
          general instruct model does, a code model often does not.
        </p>
      </div>
      <Switch
        id="tool-calling"
        checked={hasToolCalling(rows)}
        onCheckedChange={(on) => onChange(withToolCalling(rows, on, parser))}
      />
    </div>
  );
}
