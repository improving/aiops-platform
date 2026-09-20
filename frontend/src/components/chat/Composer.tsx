import { useEffect, type RefObject } from "react";
import { PaperPlaneIcon, StopIcon } from "@radix-ui/react-icons";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { formatTokens } from "@/lib/chatMetadata";

const MAX_HEIGHT_PX = 240;
/** The share of the window at which the meter turns into a warning. */
const NEARLY_FULL = 0.8;

/**
 * The message field and its one button, in one box. The field grows with
 * its text up to a bound, then scrolls. Enter sends, Shift+Enter breaks
 * the line; while an answer streams the button is Stop.
 *
 * The meter under it says how much of the target's window the
 * conversation holds, from the counts of the last answer: the request
 * that does not fit fails with an error, and nothing else warns of it.
 */
export function Composer({
  inputRef,
  value,
  onChange,
  onSubmit,
  onStop,
  busy,
  canSend,
  placeholder,
  contextUsed,
  contextLength,
  toolServers = 0,
}: {
  inputRef: RefObject<HTMLTextAreaElement | null>;
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  busy: boolean;
  canSend: boolean;
  placeholder: string;
  contextUsed?: number;
  contextLength?: number | null;
  /** How many tool servers the next message may use; said next to the
      field, because the switches are in the side panel. */
  toolServers?: number;
}) {
  useEffect(() => {
    const field = inputRef.current;
    if (!field) return;
    field.style.height = "auto";
    field.style.height = `${Math.min(field.scrollHeight, MAX_HEIGHT_PX)}px`;
  }, [inputRef, value]);

  const nearlyFull =
    !!contextUsed &&
    !!contextLength &&
    contextUsed / contextLength >= NEARLY_FULL;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      className="mt-3"
    >
      <Label htmlFor="chat-input" className="sr-only">
        Message
      </Label>
      <div className="flex items-end gap-2 rounded-md border border-input bg-transparent p-2 shadow-xs focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50 dark:bg-input/30">
        <textarea
          id="chat-input"
          ref={inputRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (
              e.key === "Enter" &&
              !e.shiftKey &&
              !e.nativeEvent.isComposing
            ) {
              e.preventDefault();
              onSubmit();
            }
          }}
          rows={1}
          placeholder={placeholder}
          className="max-h-60 min-h-9 flex-1 resize-none bg-transparent px-1 py-1.5 text-sm outline-none placeholder:text-muted-foreground"
        />
        {busy ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onStop}
            icon={<StopIcon className="h-4 w-4" />}
          >
            Stop
          </Button>
        ) : (
          <Button
            type="submit"
            size="sm"
            disabled={!canSend}
            icon={<PaperPlaneIcon className="h-4 w-4" />}
          >
            Send
          </Button>
        )}
      </div>
      <div className="mt-1 flex justify-between gap-4 text-xs text-muted-foreground">
        <span>
          Enter to send, Shift+Enter for a new line
          {toolServers > 0 && (
            <span data-testid="chat-tools-on" className="ml-2 font-medium">
              · {toolServers}{" "}
              {toolServers === 1 ? "tool server" : "tool servers"} on
            </span>
          )}
        </span>
        {!!contextUsed && !!contextLength && (
          <span
            data-testid="chat-context"
            className={
              nearlyFull ? "font-medium text-amber-600 dark:text-amber-400" : ""
            }
          >
            {formatTokens(contextUsed)} of {formatTokens(contextLength)} tokens
            {nearlyFull && ": nearly full, clear the conversation soon"}
          </span>
        )}
      </div>
    </form>
  );
}
