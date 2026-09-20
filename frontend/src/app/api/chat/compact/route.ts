import { APICallError, generateText, RetryError } from "ai";
import { backendHeaders, chatProvider } from "@/lib/chatBackend";
import {
  COMPACTION_INSTRUCTIONS,
  MAX_TRANSCRIPT_CHARS,
} from "@/lib/compaction";

export const runtime = "nodejs";
// A CPU model writes slowly; a summary is a few hundred tokens.
export const maxDuration = 300;

// `maxDuration` is a hint for a hosting platform; the chart runs the
// standalone server, so the limit is set here.
const SERVER_TIMEOUT_MS = 150_000;
const SUMMARY_TOKENS = 700;

type CompactBody = { model?: string; transcript?: string };

/**
 * The summary of the older turns of a playground conversation
 * (`src/lib/compaction.ts`). One call with no tools and no stream,
 * through the same backend path as chat, so the role check, the
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
    const result = await generateText({
      model: chatProvider(headers).chatModel(body.model),
      instructions: COMPACTION_INSTRUCTIONS,
      prompt: `The conversation so far:\n\n${body.transcript}\n\nWrite the summary.`,
      // A summary must be the same each time, not inventive.
      temperature: 0,
      maxOutputTokens: SUMMARY_TOKENS,
      // The browser's own limit aborts the request, and with it this call.
      abortSignal: AbortSignal.any([
        req.signal,
        AbortSignal.timeout(SERVER_TIMEOUT_MS),
      ]),
    });
    const summary = result.text.trim();
    if (!summary) {
      return Response.json(
        { detail: "The model wrote no summary" },
        { status: 502 }
      );
    }
    return Response.json({
      summary,
      summaryTokens: result.usage.outputTokens,
      inputTokens: result.usage.inputTokens,
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
