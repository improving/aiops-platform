import { readFileSync } from "node:fs";
import { test, expect } from "../fixtures";
import { UsagePage } from "../pages/usage";

// The TEST_MODE backend runs with AIOPS_CHAT_MOCK (playwright.config), which
// serves three canned spend-log rows for "inst-mock": two for the caller
// (dev@example.test, who is the dev admin in AUTH_MODE=disabled) and one for
// "someone@example.com" (backend/api/organizations.py _mock_usage_rows).

test.describe("usage page", () => {
  test("shows totals, by-target and by-user tables from the mock rows", async ({
    page,
  }) => {
    const usage = new UsagePage(page);
    await usage.open();
    await usage.expectHeading("Usage");

    await expect(usage.requestsTotal).toHaveText("3");
    await expect(usage.promptTokensTotal).toHaveText("40");
    await expect(usage.completionTokensTotal).toHaveText("80");
    await expect(usage.spendTotal).toHaveText("$0.06");

    const targetRows = usage.byTargetTable.locator("tbody tr");
    await expect(targetRows).toHaveCount(1);
    await expect(targetRows.first()).toContainText("Mock model");

    const userRows = usage.byUserTable.locator("tbody tr");
    await expect(userRows).toHaveCount(3);
    await expect(usage.byUserTable).toContainText("dev@example.test");
    await expect(usage.byUserTable).toContainText("someone@example.com");
  });

  test("switching the period reloads the tables", async ({ page }) => {
    const usage = new UsagePage(page);
    await usage.open();
    await expect(usage.requestsTotal).toHaveText("3");

    await usage.selectPeriod("Last 7 days");
    await expect(usage.periodSelect).toContainText("Last 7 days");
    // Mock mode serves the same three rows regardless of `days`.
    await expect(usage.requestsTotal).toHaveText("3");
  });

  test("Download CSV saves the by-user rows", async ({ page }) => {
    const usage = new UsagePage(page);
    await usage.open();
    await expect(usage.requestsTotal).toHaveText("3");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      usage.downloadButton.click(),
    ]);
    expect(download.suggestedFilename()).toBe("usage-last-30-days.csv");
    const path = await download.path();
    const text = readFileSync(path!, "utf8");
    const lines = text.trim().split(/\r?\n/);
    expect(lines[0]).toBe(
      "day,user,target,model,requests,prompt_tokens,completion_tokens,spend_usd"
    );
    expect(lines).toHaveLength(4);
    expect(text).toContain("dev@example.test");
  });

  test("Download CSV quotes a target label with a comma and a quote", async ({
    page,
  }) => {
    const row = {
      day: "2026-01-01",
      user: "dev@example.test",
      target: "inst-mock",
      label: 'a, "b"',
      model: "mock-model",
      requests: 1,
      prompt_tokens: 10,
      completion_tokens: 20,
      spend: 0.01,
    };
    await page.route("**/api/v1alpha1/organizations/current/usage**", (route) =>
      route.fulfill({
        json: {
          days: 30,
          since: "2026-01-01T00:00:00Z",
          until: "2026-01-31T00:00:00Z",
          scope: "organization",
          capped: false,
          totals: {
            requests: row.requests,
            prompt_tokens: row.prompt_tokens,
            completion_tokens: row.completion_tokens,
            spend: row.spend,
          },
          by_target: [
            {
              target: row.target,
              label: row.label,
              model: row.model,
              requests: row.requests,
              prompt_tokens: row.prompt_tokens,
              completion_tokens: row.completion_tokens,
              spend: row.spend,
            },
          ],
          rows: [row],
        },
      })
    );
    const usage = new UsagePage(page);
    await usage.open();
    await expect(usage.requestsTotal).toHaveText("1");
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      usage.downloadButton.click(),
    ]);
    const path = await download.path();
    const text = readFileSync(path!, "utf8");
    expect(text).toContain('"a, ""b"""');
  });

  test("the header links to the Usage page", async ({ page }) => {
    const usage = new UsagePage(page);
    await usage.goto("/");
    await usage.navLink("Usage").click();
    await expect(page).toHaveURL(/\/usage$/);
    await usage.expectHeading("Usage");
  });
});
