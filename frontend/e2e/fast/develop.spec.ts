import { test, expect } from "../fixtures";
import { AppShell } from "../pages/app-shell";

test.describe("develop page", () => {
  test("explains that Langflow is not configured", async ({ page }) => {
    const shell = new AppShell(page);
    await shell.goto("/develop");
    await shell.expectHeading("Interactively Develop AI Applications");
    await expect(page.getByText("Langflow is not configured")).toBeVisible();
    await expect(
      page.getByText("NEXT_PUBLIC_LANGFLOW_URL").first()
    ).toBeVisible();
    await expect(page.locator("iframe")).toHaveCount(0);
  });
});
