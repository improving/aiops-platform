import { test, expect } from "../fixtures";
import { AppShell } from "../pages/app-shell";

test.use({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
});

const paths = [
  "/",
  "/models/catalog",
  "/models/endpoints",
  "/notebooks/new",
  "/vector-databases/catalog",
];

test.describe("mobile layout", () => {
  for (const path of paths) {
    test(`${path} has no horizontal overflow`, async ({ page }) => {
      const shell = new AppShell(page);
      await shell.goto(path);
      await expect(shell.heading).toBeVisible();
      await shell.waitForLoaded();
      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));
      expect(
        overflow.scrollWidth,
        JSON.stringify(overflow)
      ).toBeLessThanOrEqual(overflow.clientWidth);
    });
  }

  test("the hamburger opens the menu and navigates", async ({ page }) => {
    const shell = new AppShell(page);
    await shell.goto("/");
    await expect(shell.mobileMenuButton).toBeVisible();
    await shell.mobileMenuButton.click();
    const sheet = shell.dialog();
    await expect(sheet).toBeVisible();
    await sheet.getByRole("link", { name: "Notebooks" }).click();
    await expect(page).toHaveURL(/\/notebooks$/);
    await shell.expectHeading("Notebooks");
    await expect(sheet).toBeHidden();
  });
});
