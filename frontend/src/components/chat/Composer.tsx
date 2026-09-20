import { useEffect, type ReactNode, type RefObject } from "react";
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
  tools,
  actions,
  onCompact,
  compacting = false,
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
  /** The tools of the next message (`ChatTools`): a button, what is on
      as chips, and a popover, in the row under the field. */
  tools?: ReactNode;
  /** What is needed now and then, as icon buttons at the end of the
      row: the code of this request, the settings, clear. */
  actions?: ReactNode;
  /** Summarize the older turns now; absent when there is nothing to
      compact. */
  onCompact?: () => void;
  compacting?: boolean;
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
          aria-describedby="chat-input-hint"
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
      <div className="mt-1.5 flex items-center justify-between gap-4 text-xs text-muted-foreground">
        <div className="flex min-w-0 flex-wrap items-center gap-2">{tools}</div>
        <span className="flex shrink-0 flex-wrap items-center justify-end gap-2">
          {!!contextUsed && !!contextLength && (
            <span
              data-testid="chat-context"
              className={
                nearlyFull
                  ? "flex items-center gap-1.5 font-medium text-amber-600 dark:text-amber-400"
                  : "flex items-center gap-1.5"
              }
            >
              <WindowRing share={contextUsed / contextLength} />
              {formatTokens(contextUsed)} of {formatTokens(contextLength)}{" "}
              tokens
              {nearlyFull &&
                (onCompact
                  ? ": nearly full, compact the conversation"
                  : ": nearly full, clear the conversation soon")}
            </span>
          )}
          {(onCompact || compacting) && (
            <button
              type="button"
              className="font-medium underline disabled:no-underline disabled:opacity-60"
              disabled={compacting || busy}
              onClick={onCompact}
            >
              {compacting ? "Compacting…" : "Compact"}
            </button>
          )}
          {actions && (
            <span className="flex items-center gap-0.5 border-l pl-2">
              {actions}
            </span>
          )}
        </span>
      </div>
      <p id="chat-input-hint" className="sr-only">
        Enter to send, Shift+Enter for a new line
      </p>
    </form>
  );
}

/** How full the model's window is, at a glance; the numbers are next to
    it for whoever wants them. */
function WindowRing({ share }: { share: number }) {
  const radius = 6;
  const around = 2 * Math.PI * radius;
  const filled = Math.min(Math.max(share, 0), 1) * around;
  return (
    <svg
      aria-hidden
      viewBox="0 0 16 16"
      className="h-3.5 w-3.5 -rotate-90"
      fill="none"
      strokeWidth="2.5"
    >
      <circle cx="8" cy="8" r={radius} className="stroke-muted" />
      <circle
        cx="8"
        cy="8"
        r={radius}
        stroke="currentColor"
        strokeDasharray={`${filled} ${around}`}
        strokeLinecap="round"
      />
    </svg>
  );
}
