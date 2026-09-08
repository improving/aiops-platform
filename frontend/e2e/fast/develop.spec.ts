import { test, expect } from "../fixtures";
import { DevelopPage } from "../pages/develop";

test.describe("develop page", () => {
  test("explains that Langflow is not configured", async ({ page }) => {
    const develop = new DevelopPage(page);
    await develop.open();
    await develop.expectHeading("Interactively Develop AI Applications");
    await expect(develop.notConfigured).toBeVisible();
    await expect(
      page.getByText("NEXT_PUBLIC_LANGFLOW_URL").first()
    ).toBeVisible();
    await expect(develop.iframe).toHaveCount(0);
    // No Langflow, nothing to provision: the panel stays away too.
    await expect(develop.panel).toHaveCount(0);
  });
});
