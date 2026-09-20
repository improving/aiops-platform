import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

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
  autoCompact,
  onAutoCompactChange,
  windowKnown,
  askFirst,
  onAskFirstChange,
  toolsBlocked,
}: {
  system: string;
  onSystemChange: (value: string) => void;
  /** "" is the model's default. */
  temperature: string;
  onTemperatureChange: (value: string) => void;
  /** "" is the model's default. */
  maxTokens: string;
  onMaxTokensChange: (value: string) => void;
  /** Compact before a send when the window is nearly full. */
  autoCompact: boolean;
  onAutoCompactChange: (on: boolean) => void;
  /** The target says how large its window is; without that, automatic
      compaction cannot know when to act. */
  windowKnown: boolean;
  /** Ask before each tool call; null when the tools cannot be used. */
  askFirst: boolean;
  onAskFirstChange: (on: boolean) => void;
  toolsBlocked: boolean;
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
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <Switch
            id="chat-auto-compact"
            checked={autoCompact}
            onCheckedChange={onAutoCompactChange}
          />
          <Label htmlFor="chat-auto-compact">Compact automatically</Label>
        </div>
        <p className="text-xs text-muted-foreground">
          From three quarters of the model&apos;s window on, the older turns are
          summarized before your next message. You can undo it.
          {autoCompact &&
            !windowKnown &&
            " This target does not say how large its window is, so use Compact under the message field."}
        </p>
      </div>
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <Switch
            id="chat-ask-first"
            aria-label="Ask before each tool call"
            checked={askFirst}
            disabled={toolsBlocked}
            onCheckedChange={onAskFirstChange}
          />
          <Label htmlFor="chat-ask-first">Ask before each tool call</Label>
        </div>
        <p className="text-xs text-muted-foreground">
          A tool can change data. You see the call and its input first.
        </p>
      </div>
    </>
  );
}
