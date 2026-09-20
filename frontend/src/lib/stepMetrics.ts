import type {
  FinishReason,
  LanguageModelUsage,
  StepResultPerformance,
} from "ai";
import type { ChatMetadata } from "@/lib/chatMetadata";

type Step = {
  performance: StepResultPerformance;
  usage: LanguageModelUsage;
  finishReason: FinishReason;
};

/**
 * The speed figures of one answer, from the `finish-step` parts as they
 * pass. The SDK's own timings, not a timer here, so a reasoning model's
 * first output counts as the first token too.
 *
 * With tools an answer is several model calls. Then the wait the user
 * felt is the first step's time to first output, the speed is all
 * output tokens over all the time spent generating (not the last step's
 * alone), and the conversation's size is what the last step held: the
 * usage total counts the prompt once for every step.
 */
export function stepMetrics(maxSteps: number) {
  const steps: Step[] = [];
  return {
    add(step: Step) {
      steps.push(step);
    },
    metadata(totalUsage: LanguageModelUsage): ChatMetadata {
      const first = steps.at(0);
      const last = steps.at(-1);
      const base: ChatMetadata = {
        ttftMs: first?.performance.timeToFirstOutputMs,
        inputTokens: totalUsage.inputTokens,
        outputTokens: totalUsage.outputTokens,
      };
      if (steps.length <= 1) {
        return {
          ...base,
          totalMs: first?.performance.responseTimeMs,
          tokensPerSecond: first?.performance.outputTokensPerSecond,
        };
      }
      let totalMs = 0;
      let generatingMs = 0;
      for (const { performance } of steps) {
        totalMs += performance.responseTimeMs;
        generatingMs +=
          performance.responseTimeMs - (performance.timeToFirstOutputMs ?? 0);
      }
      const output = totalUsage.outputTokens;
      const held = last?.usage;
      return {
        ...base,
        totalMs,
        tokensPerSecond:
          output && generatingMs > 0
            ? (output * 1000) / generatingMs
            : undefined,
        steps: steps.length,
        // The loop was cut, not finished: the model still wanted a tool.
        toolLimit:
          steps.length >= maxSteps && last?.finishReason === "tool-calls"
            ? true
            : undefined,
        contextTokens:
          held?.inputTokens !== undefined && held.outputTokens !== undefined
            ? held.inputTokens + held.outputTokens
            : undefined,
      };
    },
  };
}
