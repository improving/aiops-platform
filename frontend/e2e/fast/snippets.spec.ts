import { test, expect } from "../fixtures";
import { AppShell } from "../pages/app-shell";

// The fast backend has no instances, so the shared copy button is
// exercised on the model page, which shows the model id with one.
test.describe("copy buttons", () => {
  test("the model page offers to copy the model id and confirms with a toast", async ({
    page,
    api,
    context,
  }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const [model] = await api.models();
    const shell = new AppShell(page);
    await shell.goto(`/models/${model.id}`);
    await shell.waitForLoaded();
    await page.getByRole("button", { name: "Copy model id" }).click();
    await expect(shell.toast(/Copied/)).toBeVisible();
    const text = await page.evaluate(() => navigator.clipboard.readText());
    expect(text).toBe(model.modelId);
  });

  test("a clipboard write failure shows the Copy failed toast", async ({
    page,
    api,
  }) => {
    await page.addInitScript(() => {
      navigator.clipboard.writeText = () => Promise.reject(new Error("denied"));
    });
    const [model] = await api.models();
    const shell = new AppShell(page);
    await shell.goto(`/models/${model.id}`);
    await shell.waitForLoaded();
    await page.getByRole("button", { name: "Copy model id" }).click();
    await expect(shell.toast(/Copy failed/)).toBeVisible();
  });
});
