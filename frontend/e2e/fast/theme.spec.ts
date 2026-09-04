import { test, expect } from "../fixtures";
import { AppShell } from "../pages/app-shell";

// Start from a dark system preference so "Light" is a real transition.
test.use({ colorScheme: "dark" });

test.describe("theme", () => {
  test("follows the system preference by default", async ({ page }) => {
    const shell = new AppShell(page);
    await shell.goto("/");
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  });

  test("Light and Dark persist across reloads", async ({ page }) => {
    const shell = new AppShell(page);
    await shell.goto("/");
    const html = page.locator("html");
    await expect(html).toHaveClass(/\bdark\b/);

    await shell.chooseTheme("Light");
    await expect(html).toHaveClass(/\blight\b/);
    await expect(html).not.toHaveClass(/\bdark\b/);
    await expect(html).toHaveAttribute("style", /color-scheme:\s*light/);

    await page.reload();
    await expect(html).toHaveClass(/\blight\b/);
    expect(await page.evaluate(() => localStorage.getItem("theme"))).toBe(
      "light"
    );

    await shell.chooseTheme("Dark");
    await expect(html).toHaveClass(/\bdark\b/);
    await page.reload();
    await expect(html).toHaveClass(/\bdark\b/);
    expect(await page.evaluate(() => localStorage.getItem("theme"))).toBe(
      "dark"
    );
  });

  test("System returns to the preference", async ({ page }) => {
    const shell = new AppShell(page);
    await shell.goto("/");
    await shell.chooseTheme("Light");
    await expect(page.locator("html")).toHaveClass(/\blight\b/);
    await shell.chooseTheme("System");
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
  });
});
