import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import {
  convertToModelMessages,
  createUIMessageStreamResponse,
  streamText,
  toUIMessageStream,
  type UIMessage,
} from "ai";
import { auth } from "@/auth";
import { backendUrl } from "@/lib/backend";

export const runtime = "nodejs";
// A CPU model streams slowly; do not cut the answer short.
export const maxDuration = 300;

type ChatBody = {
  messages: UIMessage[];
  model?: string;
  system?: string;
  temperature?: number;
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

  const provider = createOpenAICompatible({
    name: "aiops",
    baseURL: `${backendUrl()}/v1alpha1`,
    headers,
  });

  const result = streamText({
    model: provider.chatModel(body.model),
    instructions: body.system?.trim() || undefined,
    messages: await convertToModelMessages(body.messages),
    temperature: body.temperature,
  });

  return createUIMessageStreamResponse({
    stream: toUIMessageStream({
      stream: result.stream,
      // Show the backend's detail (503 no endpoint, 502 unreachable) in
      // the chat instead of the generic "An error occurred".
      onError: (error) =>
        error instanceof Error ? error.message : String(error),
    }),
  });
}
