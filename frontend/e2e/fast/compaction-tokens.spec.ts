import { expect, test } from "@playwright/test";
import { summaryTextTokens } from "../../src/lib/compaction";

// The marker says how many tokens the SUMMARY has. A reasoning model's
// output count holds its thinking too, which never comes back with a
// request, so the count must be the text alone.
test.describe("tokens of a compaction summary", () => {
  const summary = "x".repeat(1400); // about 400 tokens

  test("the model's own text count wins", () => {
    const usage = {
      outputTokens: 2651,
      outputTokenDetails: { textTokens: 380, reasoningTokens: 2271 },
    };
    expect(summaryTextTokens(summary, usage, true)).toBe(380);
  });

  test("without thinking the output count is exact", () => {
    expect(summaryTextTokens(summary, { outputTokens: 412 }, false)).toBe(412);
  });

  test("the reasoning count is taken off the output", () => {
    const usage = {
      outputTokens: 2651,
      outputTokenDetails: { reasoningTokens: 2300 },
    };
    expect(summaryTextTokens(summary, usage, true)).toBe(351);
  });

  test("a model that thought and reports no detail gets an estimate", () => {
    expect(summaryTextTokens(summary, { outputTokens: 2651 }, true)).toBe(400);
    // Never more than the model wrote in all.
    expect(summaryTextTokens(summary, { outputTokens: 300 }, true)).toBe(300);
    expect(summaryTextTokens(summary, {}, true)).toBe(400);
  });
});
