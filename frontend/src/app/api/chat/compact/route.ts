import { APICallError, RetryError, streamText } from "ai";
import { backendHeaders, chatProvider } from "@/lib/chatBackend";
import {
  COMPACTION_INSTRUCTIONS,
  MAX_TRANSCRIPT_CHARS,
  summaryTextTokens,
  summaryTokens,
} from "@/lib/compaction";

export const runtime = "nodejs";
// A CPU model writes slowly; a summary is a few hundred tokens.
export const maxDuration = 300;

// `maxDuration` is a hint for a hosting platform; the chart runs the
// standalone server, so the limit is set here.
const SERVER_TIMEOUT_MS = 150_000;

type CompactBody = {
  model?: string;
  transcript?: string;
  /** The target's window in tokens, when it is known. */
  window?: number | null;
};

/**
 * The summary of the older turns of a playground conversation
 * (`src/lib/compaction.ts`). One call with no tools, through the same
 * backend path as chat, so the role check, the
 * organization's scope and the spend attribution are those of a chat
 * request. The instruction is the platform's and not the user's system
 * prompt: that one tells the model how to answer, not how to summarize.
 */
export async function POST(req: Request) {
  const body = (await req.json()) as CompactBody;
  if (!body.model || typeof body.transcript !== "string") {
    return Response.json(
      { detail: "model and transcript are required" },
      { status: 400 }
    );
  }
  if (body.transcript.length > MAX_TRANSCRIPT_CHARS) {
    return Response.json(
      { detail: "The transcript is too long" },
      { status: 413 }
    );
  }
  const headers = await backendHeaders();
  if (!headers) {
    return Response.json({ detail: "Not signed in" }, { status: 401 });
  }
  try {
    // Streamed to here, and answered as one JSON document. A summary by
    // a reasoning model takes a minute (it thinks first), and the backend
    // reads a non-streamed answer of the proxy with a limit of 60 s; a
    // stream has none, which chat needs for slow models anyway.
    let failure: unknown;
    const result = streamText({
      model: chatProvider(headers).chatModel(body.model),
      instructions: COMPACTION_INSTRUCTIONS,
      prompt: `The conversation so far:\n\n${body.transcript}\n\nWrite the summary.`,
      // A summary must be the same each time, not inventive.
      temperature: 0,
      maxOutputTokens: summaryTokens(body.window),
      // The browser's own limit aborts the request, and with it this call.
      abortSignal: AbortSignal.any([
        req.signal,
        AbortSignal.timeout(SERVER_TIMEOUT_MS),
      ]),
      onError: ({ error }) => {
        failure = error;
      },
    });
    const [text, usage, finishReason, finalStep] = await Promise.all([
      result.text,
      result.usage,
      result.finishReason,
      result.finalStep,
    ]).catch((error: unknown) => {
      // The stream's own error says why; the promise only says "no output".
      throw failure ?? error;
    });
    if (failure) throw failure;
    const summary = text.trim();
    if (!summary) {
      return Response.json(
        {
          detail:
            finishReason === "length"
              ? "The model used its whole answer for thinking and wrote no summary"
              : "The model wrote no summary",
        },
        { status: 502 }
      );
    }
    return Response.json({
      summary,
      // The text alone: the thinking does not come back with a request.
      summaryTokens: summaryTextTokens(
        summary,
        usage,
        !!finalStep.reasoningText
      ),
      inputTokens: usage.inputTokens,
    });
  } catch (error) {
    const cause = RetryError.isInstance(error) ? error.lastError : error;
    const detail = APICallError.isInstance(cause)
      ? `The model answered ${cause.statusCode ?? "an error"}: ${(cause.responseBody ?? cause.message).slice(0, 300)}`
      : error instanceof Error
        ? error.message
        : "The summary failed";
    return Response.json({ detail }, { status: 502 });
  }
}
