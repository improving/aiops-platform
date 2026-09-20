import {
  getToolOrDynamicToolName,
  type DynamicToolUIPart,
  type ToolUIPart,
} from "ai";
import { CodeSnippet } from "@/components/CodeSnippet";

export type ToolPart = ToolUIPart | DynamicToolUIPart;

type ToolState = "running" | "done" | "failed";

function toolState(part: ToolPart): ToolState {
  if (part.state === "output-available") return "done";
  if (part.state === "output-error" || part.state === "output-denied") {
    return "failed";
  }
  return "running";
}

/** Pretty JSON for an object; a string stays as it is (an MCP tool's
    text result is already meant for reading). */
function show(value: unknown): string {
  if (value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** An MCP result is `{content: [{type: "text", text}], isError}`: show
    the text parts, which is what the model reads, and fall back to the
    whole value for anything else. */
function outputText(output: unknown): string {
  if (output && typeof output === "object" && "content" in output) {
    const content = (output as { content?: unknown }).content;
    if (Array.isArray(content)) {
      const texts = content
        .filter(
          (item): item is { type: "text"; text: string } =>
            !!item &&
            typeof item === "object" &&
            (item as { type?: unknown }).type === "text" &&
            typeof (item as { text?: unknown }).text === "string"
        )
        .map((item) => item.text);
      if (texts.length > 0 && texts.length === content.length) {
        return texts.join("\n");
      }
    }
  }
  return show(output);
}

/** A tool of an MCP server reaches the model as `<server><id8>-<tool>`
    (the platform's alias: the server's name without `_`, eight hex
    characters of its id, then the first `-`). Shown as the server and
    the tool; any other name is shown as it is. */
const PLATFORM_TOOL = /^([a-z][a-z0-9]*)[0-9a-f]{8}-(.+)$/;

export function toolLabel(name: string): { server?: string; tool: string } {
  const match = PLATFORM_TOOL.exec(name);
  return match ? { server: match[1], tool: match[2] } : { tool: name };
}

const STATE_LABEL: Record<ToolState, string> = {
  running: "running…",
  done: "done",
  failed: "failed",
};

/**
 * One tool call of an answer: the tool's name and state on one line,
 * the input and the result behind it. Open while the call runs, so a
 * slow tool shows what it was asked; closed once it is done, so the
 * answer stays the main text.
 *
 * The values are shown as plain text, never highlighted: a tool's
 * result comes from outside the platform.
 */
export function ToolCallBlock({ part }: { part: ToolPart }) {
  const name = getToolOrDynamicToolName(part);
  const label = toolLabel(name);
  const state = toolState(part);
  const input = show(part.input);
  const output =
    part.state === "output-available" ? outputText(part.output) : "";
  const error =
    part.state === "output-error"
      ? part.errorText
      : part.state === "output-denied"
        ? "The call was not approved."
        : "";

  return (
    <details
      data-testid="chat-tool-call"
      data-state={state}
      open={state === "running" ? true : undefined}
      className="my-1 rounded-md border text-xs"
    >
      <summary className="flex cursor-pointer items-center gap-2 px-3 py-2">
        <span className="font-mono font-medium">
          {label.server && (
            <span className="font-normal text-muted-foreground">
              {label.server} ·{" "}
            </span>
          )}
          {label.tool}
        </span>
        <span
          className={
            state === "failed" ? "text-destructive" : "text-muted-foreground"
          }
        >
          {STATE_LABEL[state]}
        </span>
      </summary>
      <div className="flex flex-col gap-2 border-t px-3 py-2">
        {input && (
          <div>
            <div className="mb-1 text-muted-foreground">Input</div>
            <CodeSnippet label={`Input of ${name}`} code={input} wrap />
          </div>
        )}
        {output && (
          <div>
            <div className="mb-1 text-muted-foreground">Result</div>
            <CodeSnippet label={`Result of ${name}`} code={output} wrap />
          </div>
        )}
        {error && (
          <div role="alert" className="text-destructive">
            {error}
          </div>
        )}
      </div>
    </details>
  );
}
