import { memo } from "react";
import { isToolUIPart } from "ai";
import { Pencil1Icon, ReloadIcon } from "@radix-ui/react-icons";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/CopyButton";
import { Markdown } from "@/components/chat/Markdown";
import { ToolCallBlock } from "@/components/chat/ToolCallBlock";
import { speedLine, type ChatUIMessage } from "@/lib/chatMetadata";

export function messageText(message: ChatUIMessage): string {
  return message.parts
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("");
}

/** Something of this answer can be shown: text, thinking, or a tool
    call (which has a line of its own from its first moment). */
export function hasContent(message: ChatUIMessage): boolean {
  return message.parts.some(
    (part) =>
      isToolUIPart(part) ||
      ((part.type === "text" || part.type === "reasoning") && part.text !== "")
  );
}

/**
 * One turn. Memoized: a stream re-renders the panel per token, and only
 * the message that grows has new props.
 *
 * An answer with nothing to show yet renders nothing, so "the message is
 * not empty" keeps meaning "text has arrived" for the specs, and the
 * waiting row stands in for it.
 *
 * An answer's parts are shown in the order they arrived: with tools a
 * turn is several steps (thinking, a tool call, then the text), and
 * the order is the explanation. Reasoning models (qwen3, o-series)
 * stream their thinking first.
 *
 * An answer has no bubble: it is the page's main text, and its code
 * blocks and tables need the contrast a filled bubble would take away.
 *
 * The actions are for the last turn of each side only: regenerating or
 * editing an earlier one would silently drop what came after it.
 */
export const ChatMessage = memo(function ChatMessage({
  message,
  streaming,
  onRegenerate,
  onEdit,
  onContinue,
  onToolApproval,
}: {
  /** Answer a tool call that waits for approval; the last turn only. */
  onToolApproval?: (id: string, approved: boolean) => void;
  message: ChatUIMessage;
  /** This answer is still arriving: no actions, no speed line yet. */
  streaming: boolean;
  onRegenerate?: (messageId: string) => void;
  onEdit?: (messageId: string) => void;
  /** Offered when the answer stopped at the limit of tool steps. */
  onContinue?: () => void;
}) {
  const text = messageText(message);
  const isUser = message.role === "user";
  if (!isUser && !hasContent(message)) return null;
  const speed = isUser || streaming ? "" : speedLine(message.metadata);

  return (
    <div
      data-testid="chat-message"
      data-role={message.role}
      className={`group flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}
    >
      <div
        className={
          isUser
            ? "max-w-[85%] rounded-lg bg-primary px-3 py-2 break-words whitespace-pre-wrap text-primary-foreground"
            : "w-full min-w-0 py-1"
        }
      >
        {isUser
          ? text
          : message.parts.map((part, index) => {
              if (isToolUIPart(part)) {
                return (
                  <ToolCallBlock
                    key={part.toolCallId}
                    part={part}
                    onApproval={onToolApproval}
                  />
                );
              }
              if (part.type === "reasoning" && part.text) {
                return (
                  <details
                    key={index}
                    className="mb-1 text-xs text-muted-foreground"
                  >
                    <summary className="cursor-pointer">Thinking</summary>
                    <div className="mt-1 whitespace-pre-wrap">{part.text}</div>
                  </details>
                );
              }
              if (part.type === "text" && part.text) {
                return <Markdown key={index} text={part.text} />;
              }
              return null;
            })}
      </div>
      {!streaming && message.metadata?.toolLimit && (
        <p
          data-testid="chat-tool-limit"
          className="flex items-center gap-2 text-xs text-muted-foreground"
        >
          Stopped after {message.metadata.steps} tool steps.
          {onContinue && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onContinue}
            >
              Continue
            </Button>
          )}
        </p>
      )}
      {!streaming && (
        <div className="flex min-h-8 items-center gap-2 text-xs text-muted-foreground">
          {/* Hidden until the turn is hovered or holds the focus; a touch
              screen has no hover, so there they always show. */}
          <div className="flex gap-1 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100">
            {!isUser && text && <CopyButton label="answer" text={text} />}
            {onRegenerate && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-label="Regenerate answer"
                onClick={() => onRegenerate(message.id)}
                icon={<ReloadIcon className="h-4 w-4" />}
              />
            )}
            {onEdit && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                aria-label="Edit message"
                onClick={() => onEdit(message.id)}
                icon={<Pencil1Icon className="h-4 w-4" />}
              />
            )}
          </div>
          {speed && <span data-testid="chat-speed">{speed}</span>}
        </div>
      )}
    </div>
  );
});
