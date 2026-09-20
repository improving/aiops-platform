"use client";

import { formatTokens } from "@/lib/chatMetadata";
import type { CompactionInfo } from "@/lib/compaction";

/**
 * Where a conversation was compacted: from here on the model gets the
 * summary below and not the turns above it. The turns stay on the page
 * (collapsed), and Undo makes them live again; nothing is lost, the
 * conversation is only in this browser.
 */
export function CompactionMarker({
  summary,
  info,
  onUndo,
}: {
  summary: string;
  info: CompactionInfo;
  /** Absent while an answer runs, and for an older marker. */
  onUndo?: () => void;
}) {
  const figures = [
    `${info.covered} ${info.covered === 1 ? "message" : "messages"}`,
    info.tokensBefore !== undefined &&
      `the conversation held ${formatTokens(info.tokensBefore)} tokens`,
    info.summaryTokens !== undefined &&
      `the summary has ${formatTokens(info.summaryTokens)}`,
  ].filter(Boolean);
  return (
    <div
      data-testid="chat-compaction"
      className="rounded-md border border-dashed bg-muted/40 p-3 text-xs text-muted-foreground"
    >
      <div className="flex items-start justify-between gap-3">
        <p>
          <span className="font-medium text-foreground">
            Earlier conversation, summarized
            {info.automatic ? " automatically" : ""}.
          </span>{" "}
          {figures.join(" · ")}. From here on the model gets this summary, not
          the turns above.
        </p>
        {onUndo && (
          <button
            type="button"
            className="shrink-0 font-medium underline"
            onClick={onUndo}
          >
            Undo
          </button>
        )}
      </div>
      <details className="mt-2">
        <summary className="cursor-pointer">Read the summary</summary>
        <p className="mt-2 whitespace-pre-wrap text-foreground">{summary}</p>
      </details>
    </div>
  );
}
