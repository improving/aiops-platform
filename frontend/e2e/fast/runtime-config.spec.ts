import { test, expect } from "../fixtures";
import { DevelopPage } from "../pages/develop";

// The managed fast backend sets no LANGFLOW_URL, so /develop shows the card
// (develop.spec.ts). Stubbing the runtime config endpoint proves the
// runtime path: the same build embeds Langflow when the backend names it.
test.describe("runtime UI configuration", () => {
  test("the develop page embeds the Langflow URL the backend serves", async ({
    page,
    context,
  }) => {
    const langflowUrl = "https://langflow.example.test";
    await page.route("**/api/v1alpha1/config/ui", (route) =>
      route.fulfill({
        json: {
          grafanaUrl: "",
          langflowUrl,
          jaegerUrl: "",
          authMode: "disabled",
        },
      })
    );
    // The iframe must not reach the network: answer it with an empty page.
    await page.route(`${langflowUrl}/**`, (route) =>
      route.fulfill({ contentType: "text/html", body: "<html></html>" })
    );
    const develop = new DevelopPage(page);
    await develop.open();
    await expect(develop.notConfigured).toHaveCount(0);
    await expect(develop.iframe).toHaveAttribute(
      "src",
      new RegExp(`^${langflowUrl.replace(/[.]/g, "\\.")}`)
    );
    // The managed fast backend runs with AIOPS_CHAT_MOCK, so provisioning
    // answers with the canned organization and the mock model; the names
    // live behind the "Models" picker so the editor keeps the page, the
    // search matches the label too, and selecting copies the name.
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await expect(develop.panel).toContainText("OpenAI Compatible");
    await expect(develop.models).toHaveText(/Models \(1\)/);
    await expect(develop.panel).not.toContainText("inst-mock");
    await develop.models.click();
    await develop.modelSearch.fill("no such model");
    await expect(page.getByText("No model matches.")).toBeVisible();
    await develop.modelSearch.fill("mock");
    await develop.modelOption("inst-mock").click();
    await expect(develop.toast(/Copied/)).toBeVisible();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
      "inst-mock"
    );
  });

  test("the card names both the backend and the build variable", async ({
    page,
  }) => {
    const develop = new DevelopPage(page);
    await develop.open();
    await expect(develop.notConfigured).toBeVisible();
    await expect(page.getByText("LANGFLOW_URL", { exact: true })).toBeVisible();
    await expect(
      page.getByText("NEXT_PUBLIC_LANGFLOW_URL", { exact: true })
    ).toBeVisible();
  });
});
