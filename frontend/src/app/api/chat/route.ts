import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
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
import { cookies } from "next/headers";
import { auth } from "@/auth";
import { backendUrl } from "@/lib/backend";
import type { ChatMetadata } from "@/lib/chatMetadata";
import {
  DEV_USER_COOKIE,
  DEV_USER_HEADER,
  ORG_COOKIE,
  ORG_HEADER,
} from "@/lib/orgCookie";
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
};

function authDisabled(): boolean {
  return process.env.AUTH_MODE === "disabled";
}

async function accessToken(): Promise<string | undefined> {
  if (authDisabled()) return undefined;
  const session = await auth();
  // A session whose refresh was rejected is as good as none (src/proxy.ts).
  if (!session || session.error) return undefined;
  return session.accessToken;
}

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
  const token = await accessToken();
  if (!token && !authDisabled()) {
    return Response.json({ detail: "Not signed in" }, { status: 401 });
  }

  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  // The route is excluded from the proxy matcher, so it forwards the
  // organization (and, in disabled mode, the dev user) cookie itself.
  const jar = await cookies();
  const org = jar.get(ORG_COOKIE)?.value;
  if (org) headers[ORG_HEADER] = org;
  const devUser = authDisabled() ? jar.get(DEV_USER_COOKIE)?.value : undefined;
  if (devUser) headers[DEV_USER_HEADER] = devUser;

  const provider = createOpenAICompatible({
    name: "aiops",
    baseURL: `${backendUrl()}/v1alpha1`,
    headers,
    // `stream_options.include_usage`: the last chunk carries the token
    // counts the speed line and the context meter show.
    includeUsage: true,
  });

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
  const { tools, close } = resolved;
  const hasTools = Object.keys(tools).length > 0;

  const result = streamText({
    model: provider.chatModel(body.model),
    instructions:
      body.system?.trim() || (hasTools ? DEFAULT_TOOL_INSTRUCTIONS : undefined),
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
