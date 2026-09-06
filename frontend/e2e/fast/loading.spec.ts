import { test, expect } from "../fixtures";
import { AppShell } from "../pages/app-shell";

// Hold the instance list response so the skeleton is visible long enough to
// assert on, then release it and check the skeleton is gone.
test.describe("loading skeletons", () => {
  test("the model instances page shows a skeleton until the list arrives", async ({
    page,
  }) => {
    const shell = new AppShell(page);
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/api/v1alpha1/inferenceInstance", async (route) => {
      await gate;
      await route.continue();
    });
    await page.goto("/models/endpoints");
    await expect(shell.loading()).toHaveCount(1);
    release();
    await shell.waitForLoaded();
    await expect(page.getByText("No model instances yet.")).toBeVisible();
  });

  test("the usage page shows a skeleton until the report arrives", async ({
    page,
  }) => {
    const shell = new AppShell(page);
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/api/v1alpha1/organizations/current/usage**", async (route) => {
      await gate;
      await route.continue();
    });
    await page.goto("/usage");
    await expect(shell.loading()).toHaveCount(1);
    release();
    await shell.waitForLoaded();
    await expect(page.getByTestId("usage-total-requests")).toBeVisible();
  });
});
