import { test, expect, shortId } from "../fixtures";
import { TokensPage } from "../pages/tokens";

// AUTH_MODE=disabled never resolves a personal token (spec 5.1 step 1 wins),
// so the fast tier checks the page: create once, shown once, revoke.
// backend/test_tokens.py proves the token itself.

test.describe("API tokens page", () => {
  test("creates a token, shows it once and revokes it", async ({ page }) => {
    const tokens = new TokensPage(page);
    await tokens.open();
    await tokens.expectHeading("API tokens");
    await tokens.waitForLoaded();

    const name = `laptop-${shortId()}`;
    await tokens.createToken(name, "Read and write", "90 days");
    const token = (await tokens.newToken.textContent())!.trim();
    expect(token).toMatch(/^aiops_[A-Za-z0-9]{8}_[A-Za-z0-9]{32}$/);
    await expect(
      tokens.dialog().getByRole("button", { name: "Copy API token" })
    ).toBeVisible();
    await expect(
      tokens.dialog().getByRole("group", { name: "curl example" })
    ).toContainText(token);

    // Escape cannot lose the secret once it is on screen; only "Done" can
    // close the reveal.
    await page.keyboard.press("Escape");
    await expect(tokens.dialog()).toBeVisible();
    await expect(tokens.newToken).toHaveText(token);

    await tokens.doneButton.click();

    await expect(tokens.tokenRow(name)).toContainText("Active");
    await expect(tokens.tokenRow(name)).toContainText("write");
    // The secret is gone from the page once the dialog closes.
    await expect(page.getByText(token)).toHaveCount(0);
    await expect(tokens.tokenRow(name)).toContainText(
      token.slice(0, "aiops_".length + 8)
    );

    await tokens.revoke(name);
    await expect(tokens.tokenRow(name)).toContainText("Revoked");
    await expect(
      tokens.tokenRow(name).getByRole("button", { name: "Revoke" })
    ).toHaveCount(0);
  });

  test("a read token shows its scope", async ({ page }) => {
    const tokens = new TokensPage(page);
    await tokens.open();
    await tokens.waitForLoaded();
    const name = `reader-${shortId()}`;
    await tokens.createToken(name, "Read only", "30 days");
    await tokens.doneButton.click();
    await expect(tokens.tokenRow(name)).toContainText("read");
  });

  test("the user menu links to the page", async ({ page }) => {
    const tokens = new TokensPage(page);
    await tokens.goto("/");
    const menu = await tokens.openUserMenu();
    await menu.getByRole("menuitem", { name: "API tokens" }).click();
    await expect(page).toHaveURL(/\/settings\/tokens$/);
    await tokens.expectHeading("API tokens");
  });
});
