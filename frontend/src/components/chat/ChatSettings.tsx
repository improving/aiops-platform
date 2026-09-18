import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { CodeExamplesDialog } from "@/components/instances/CodeExamplesDialog";
import type { CodeExample } from "@/components/instances/CodeExamplesDialog";

const DEFAULT_TEMPERATURE = "0.7";

/**
 * What shapes the next request. Temperature and the token limit are
 * empty by default and then not sent at all: some hosted models reject
 * any value but their own, so "model default" is a state, not a number.
 */
export function ChatSettings({
  system,
  onSystemChange,
  temperature,
  onTemperatureChange,
  maxTokens,
  onMaxTokensChange,
  examples,
  onClear,
  canClear,
}: {
  system: string;
  onSystemChange: (value: string) => void;
  /** "" is the model's default. */
  temperature: string;
  onTemperatureChange: (value: string) => void;
  /** "" is the model's default. */
  maxTokens: string;
  onMaxTokensChange: (value: string) => void;
  /** Empty without a target. */
  examples: CodeExample[];
  onClear: () => void;
  canClear: boolean;
}) {
  const ownTemperature = temperature !== "";
  return (
    <>
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="chat-system">System prompt</Label>
          {system.trim() && (
            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
              Active
            </span>
          )}
        </div>
        <Textarea
          id="chat-system"
          value={system}
          onChange={(e) => onSystemChange(e.target.value)}
          rows={4}
          placeholder="How the model should behave, for every message"
        />
      </div>
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <Label id="chat-temperature-label">Temperature</Label>
          <span className="text-sm text-muted-foreground tabular-nums">
            {ownTemperature ? Number(temperature).toFixed(1) : "model default"}
          </span>
        </div>
        <Slider
          thumbLabel="Temperature"
          min={0}
          max={2}
          step={0.1}
          disabled={!ownTemperature}
          value={[Number(ownTemperature ? temperature : DEFAULT_TEMPERATURE)]}
          onValueChange={([value]) => onTemperatureChange(String(value))}
        />
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>0 repeatable · 2 varied</span>
          <span className="flex items-center gap-2">
            <Label htmlFor="chat-temperature-default" className="text-xs">
              Model default
            </Label>
            <Switch
              id="chat-temperature-default"
              size="sm"
              checked={!ownTemperature}
              onCheckedChange={(checked) =>
                onTemperatureChange(checked ? "" : DEFAULT_TEMPERATURE)
              }
            />
          </span>
        </div>
      </div>
      <div className="space-y-2">
        <Label htmlFor="chat-max-tokens">Max tokens</Label>
        <Input
          id="chat-max-tokens"
          type="number"
          min={1}
          step={1}
          value={maxTokens}
          placeholder="model default"
          onChange={(e) => onMaxTokensChange(e.target.value)}
        />
        <p className="text-xs text-muted-foreground">
          The longest answer, in tokens. An answer that reaches it stops in the
          middle.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {examples.length > 0 && (
          <CodeExamplesDialog
            triggerLabel="View code"
            examples={examples}
            title="This request from your own code"
            description="The same target and settings through the platform API. Replace <API_TOKEN> with a personal API token."
          />
        )}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onClear}
          disabled={!canClear}
        >
          Clear conversation
        </Button>
      </div>
      {examples.length > 0 && (
        <p className="text-xs text-muted-foreground">
          API tokens are made on the{" "}
          <Link href="/settings/tokens" className="underline">
            API tokens
          </Link>{" "}
          page.
        </p>
      )}
    </>
  );
}
