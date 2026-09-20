import {
  APICallError,
  convertToModelMessages,
  createUIMessageStreamResponse,
  RetryError,
  stepCountIs,
  streamText,
  toUIMessageStream,
  type TextStreamPart,
  type ToolSet,
  type UIMessage,
} from "ai";
import { backendHeaders, chatProvider } from "@/lib/chatBackend";
import type { ChatMetadata } from "@/lib/chatMetadata";
import { MAX_SUMMARY_CHARS, withSummary } from "@/lib/compaction";
import { stepMetrics } from "@/lib/stepMetrics";
import {
  DEFAULT_TOOL_INSTRUCTIONS,
  MAX_TOOL_STEPS,
  parseToolSources,
  resolveToolSources,
  ToolSourceError,
} from "@/lib/toolSources";

export const runtime = "nodejs";
// A CPU model streams slowly; do not cut the answer short.
export const maxDuration = 300;

type ChatBody = {
  messages: UIMessage[];
  model?: string;
  system?: string;
  temperature?: number;
  maxOutputTokens?: number;
  /** Where this request's tools come from (`src/lib/toolSources.ts`). */
  toolSources?: unknown;
  /** The user wants to say yes before a tool runs. */
  approveTools?: boolean;
  /** A compacted conversation: what the turns that are not sent said
      (`src/lib/compaction.ts`). */
  summary?: string;
};

/**
 * Turns the AI SDK UI message stream into the backend's OpenAI-compatible
 * chat endpoint. `model` is the chat target name (`inst-<id8>`, from
 * `GET /v1alpha1/chat/targets`); the session's bearer goes along the same
 * way `src/proxy.ts` attaches it to `/api/v1alpha1/*`.
 */
export async function POST(req: Request) {
  const body = (await req.json()) as ChatBody;
  if (!body.model) {
    return Response.json({ detail: "model is required" }, { status: 400 });
  }
  const headers = await backendHeaders();
  if (!headers) {
    return Response.json({ detail: "Not signed in" }, { status: 401 });
  }
  const provider = chatProvider(headers);

  // The tools the user turned on. A failure here is an answer of its
  // own: the chat page offers to send the message without tools.
  let resolved;
  try {
    resolved = await resolveToolSources(
      parseToolSources(body.toolSources),
      headers
    );
  } catch (error) {
    if (error instanceof ToolSourceError) {
      return Response.json({ detail: error.message }, { status: 502 });
    }
    throw error;
  }
  const { tools, close, needsApproval } = resolved;
  const hasTools = Object.keys(tools).length > 0;

  const result = streamText({
    model: provider.chatModel(body.model),
    // The summary of a compacted conversation goes into the one system
    // message, after the user's (or the default one for tools): several
    // chat templates accept no second system message.
    instructions: withSummary(
      body.system?.trim() || (hasTools ? DEFAULT_TOOL_INSTRUCTIONS : undefined),
      // The caller's own request, like `system`; only its shape is checked.
      typeof body.summary === "string"
        ? body.summary.slice(0, MAX_SUMMARY_CHARS)
        : undefined
    ),
    // A stopped answer can leave a tool call without its result in the
    // browser's copy of the conversation; the model must not see half
    // of a call.
    messages: await convertToModelMessages(body.messages, {
      tools,
      ignoreIncompleteToolCalls: true,
    }),
    temperature: body.temperature,
    maxOutputTokens: body.maxOutputTokens,
    // With tools the answer is a loop: call, read the result, go on.
    ...(hasTools ? { tools, stopWhen: stepCountIs(MAX_TOOL_STEPS) } : {}),
    // Ask first: the step ends with the call waiting, the page shows it
    // with Approve and Deny, and the answer comes back as the next
    // request, where an approved call runs and a denied one is told to
    // the model. The member's switch asks for every call; without it
    // the admin's setting of each server decides (never, writes, always).
    ...(hasTools
      ? {
          toolApproval: ({ toolCall }: { toolCall: { toolName: string } }) =>
            body.approveTools || needsApproval(toolCall.toolName)
              ? ("user-approval" as const)
              : ("not-applicable" as const),
        }
      : {}),
    // The MCP client lives as long as the loop, however it ends.
    onFinish: close,
    onError: close,
    onAbort: close,
  });

  // `messageMetadata` sees only the `start` and `finish` parts, and the
  // timings live on the `finish-step` parts, which come first: keep
  // them as they pass (`stepMetrics` says what it makes of several).
  const metrics = stepMetrics(MAX_TOOL_STEPS);
  const stream = result.stream.pipeThrough(
    new TransformStream<TextStreamPart<ToolSet>, TextStreamPart<ToolSet>>({
      transform(part, controller) {
        if (part.type === "finish-step") metrics.add(part);
        controller.enqueue(part);
      },
    })
  );

  return createUIMessageStreamResponse({
    stream: toUIMessageStream({
      stream,
      messageMetadata: ({ part }): ChatMetadata | undefined =>
        part.type === "finish" ? metrics.metadata(part.totalUsage) : undefined,
      // Show the backend's detail (503 no endpoint, 502 unreachable) in
      // the chat instead of the generic "An error occurred".
      onError: (error) => {
        // The SDK keeps only `{"error":{"message"}}` bodies, so read
        // FastAPI's `detail` back from the response body, through the
        // retry wrapper, and prefix the status for the chat page.
        const inner = RetryError.isInstance(error) ? error.lastError : error;
        if (APICallError.isInstance(inner) && inner.responseBody) {
          try {
            const detail = JSON.parse(inner.responseBody)?.detail;
            if (typeof detail === "string") {
              return `${inner.statusCode}: ${detail}`;
            }
          } catch {
            // Not JSON: fall through to the message.
          }
        }
        return error instanceof Error ? error.message : String(error);
      },
    }),
  });
}
