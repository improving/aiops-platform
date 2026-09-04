import { test, expect, FAILED_RESOURCE, fixme } from "../fixtures";
import { AppShell } from "../pages/app-shell";
import { NotebookDetailsPage } from "../pages/notebooks";

// These pages request ids the backend rejects; the failed fetch is expected.
test.use({ allowedConsoleErrors: [FAILED_RESOURCE] });

test.describe("error pages", () => {
  test("an unknown model shows the not-found message and an error toast", async ({
    page,
  }) => {
    const shell = new AppShell(page);
    await shell.goto("/models/does-not-exist");
    await shell.expectHeading("Model Details");
    await expect(page.getByText("No model found")).toBeVisible();
    await expect(shell.toast(/API Error/)).toBeVisible();
  });

  test("an unknown notebook shows the not-found message", async ({ page }) => {
    const details = new NotebookDetailsPage(page);
    await details.open("does-not-exist");
    await details.expectHeading("Notebook Details");
    await expect(details.notFound).toBeVisible();
    await expect(details.toast(/API Error/)).toBeVisible();
  });

  test("an unknown route shows the not-found page with a way home", async ({
    page,
  }) => {
    const shell = new AppShell(page);
    const response = await page.goto("/nonexistent");
    expect(response?.status()).toBe(404);
    await expect(
      page.getByRole("link", { name: /back to home/i })
    ).toBeVisible();
    await page.getByRole("link", { name: /back to home/i }).click();
    await expect(page).toHaveURL(/\/$/);
    await shell.expectHeading("Welcome to AI Hub");
  });
});
