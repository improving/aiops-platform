import type { UIMessage } from "ai";

/** What the route handler attaches to an answer when it finishes
    (`src/app/api/chat/route.ts`): the SDK's own step timings and the
    token counts the server reported. Every part is optional: a server
    that sends no usage chunk leaves the counts out. */
export type ChatMetadata = {
  ttftMs?: number;
  totalMs?: number;
  tokensPerSecond?: number;
  inputTokens?: number;
  outputTokens?: number;
  /** Model calls of this answer; above one when tools ran. */
  steps?: number;
  /** What the last step held (its input and output tokens): the
      conversation the next request starts from. With one step it is
      the two counts above, so it is only set for a tool loop, where
      those are sums over the steps and count the prompt once a step. */
  contextTokens?: number;
  /** The answer stopped at the limit of tool steps, not at its end. */
  toolLimit?: boolean;
};

export type ChatUIMessage = UIMessage<ChatMetadata>;

const number = new Intl.NumberFormat("en-US");

export function formatTokens(count: number): string {
  return number.format(count);
}

function seconds(ms: number): string {
  return ms < 10_000
    ? `${(ms / 1000).toFixed(1)} s`
    : `${Math.round(ms / 1000)} s`;
}

/** Generation speed: the SDK's figure, else output tokens over the time
    after the first token. */
export function tokensPerSecond(meta: ChatMetadata): number | undefined {
  if (meta.tokensPerSecond && Number.isFinite(meta.tokensPerSecond)) {
    return meta.tokensPerSecond;
  }
  const { outputTokens, totalMs, ttftMs } = meta;
  if (!outputTokens || !totalMs) return undefined;
  const generating = totalMs - (ttftMs ?? 0);
  return generating > 0 ? (outputTokens * 1000) / generating : undefined;
}

/** "0.4 s to first token · 93 tok/s · 212 tokens", with only the parts
    that are known; empty when none is. */
export function speedLine(meta: ChatMetadata | undefined): string {
  if (!meta) return "";
  const parts: string[] = [];
  if (meta.ttftMs !== undefined) {
    parts.push(`${seconds(meta.ttftMs)} to first token`);
  }
  const speed = tokensPerSecond(meta);
  if (speed !== undefined) {
    parts.push(`${speed >= 10 ? Math.round(speed) : speed.toFixed(1)} tok/s`);
  }
  if (meta.outputTokens !== undefined) {
    parts.push(`${formatTokens(meta.outputTokens)} tokens`);
  }
  if (meta.steps !== undefined && meta.steps > 1) {
    parts.push(`${meta.steps} steps`);
  }
  return parts.join(" · ");
}

/** Tokens the conversation held after this answer: what the next request
    starts from. */
export function contextUsed(
  meta: ChatMetadata | undefined
): number | undefined {
  if (meta?.contextTokens !== undefined) return meta.contextTokens;
  if (meta?.inputTokens === undefined || meta.outputTokens === undefined) {
    return undefined;
  }
  return meta.inputTokens + meta.outputTokens;
}
