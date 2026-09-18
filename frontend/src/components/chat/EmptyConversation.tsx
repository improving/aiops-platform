import { Button } from "@/components/ui/button";
import { formatTokens } from "@/lib/chatMetadata";
import type { ChatTarget } from "@/types/models";

const CODING_PROMPTS = [
  "Write a Python function that merges two sorted lists, with tests.",
  "Explain what a Kubernetes startup probe does, with a YAML example.",
  "Review this code for bugs: paste it after this line.",
  "Write a SQL query for the top five customers by revenue per month.",
];

const GENERAL_PROMPTS = [
  "Summarize the trade-offs between RAG and fine-tuning in five points.",
  "Draft a short release note for a new login page.",
  "Explain vector databases to a backend engineer.",
  "Give me a table that compares three ways to serve an LLM.",
];

/**
 * What an empty conversation shows instead of a blank box: what is on the
 * other end, and a few prompts to start from. A prompt fills the field
 * and does not send, so it can be changed first.
 */
export function EmptyConversation({
  target,
  onPick,
}: {
  target: ChatTarget;
  onPick: (prompt: string) => void;
}) {
  const prompts = /cod(e|er)/i.test(`${target.label} ${target.model}`)
    ? CODING_PROMPTS
    : GENERAL_PROMPTS;
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
      <div>
        <p className="font-medium">{target.label}</p>
        <p className="text-sm text-muted-foreground">
          {target.model}
          {target.context_length
            ? ` · ${formatTokens(target.context_length)} token window`
            : ""}
        </p>
      </div>
      <div
        role="group"
        aria-label="Starter prompts"
        className="grid w-full gap-2 sm:grid-cols-2"
      >
        {prompts.map((prompt) => (
          <Button
            key={prompt}
            type="button"
            variant="outline"
            className="h-auto justify-start py-2 text-left font-normal whitespace-normal"
            onClick={() => onPick(prompt)}
          >
            {prompt}
          </Button>
        ))}
      </div>
    </div>
  );
}
