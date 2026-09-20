import { test, expect, shortId, FAILED_RESOURCE } from "../fixtures";
import { McpServersPage } from "../pages/mcp-servers";

// OAuth sign-in to an MCP server. With AIOPS_CHAT_MOCK the backend's
// authorization URL is the UI's own callback page with `code=mock`, so the
// browser makes the whole round trip: start, leave, come back, exchange.

test.describe("MCP server with OAuth sign-in", () => {
  test("an admin adds it with no connection test, and a member signs in", async ({
    page,
  }) => {
    const mcp = new McpServersPage(page);
    await mcp.open();
    await mcp.waitForLoaded();
    const name = `oauth_${shortId()}`;

    await mcp.openAddDialog();
    const dialog = page.getByRole("dialog", { name: "Add MCP server" });
    await mcp.fillConnection({ name, url: "https://mcp.example.com/mcp" });
    await dialog.getByLabel("OAuth: each member signs in").check();
    // Nobody has a token yet: no test, no tool list, no shared credential.
    await expect(
      dialog.getByRole("button", { name: "Test connection" })
    ).toHaveCount(0);
    await expect(dialog.getByLabel("Client ID (optional)")).toBeVisible();
    await dialog.getByRole("button", { name: "Add server" }).click();
    await expect(dialog).toBeHidden();
    await expect(mcp.serverRow(name)).toBeVisible();

    await mcp.runAction(name, "Sign in");
    const connect = page.getByRole("dialog", { name: `Connect ${name}` });
    await expect(connect).toContainText("never sees your password");
    await connect.getByRole("button", { name: `Sign in to ${name}` }).click();

    // Out to the (mock) authorization server and back through the
    // callback page, which returns to where the sign-in started.
    await expect(page).toHaveURL(/\/mcp-servers$/);
    await expect(page.getByText(`Signed in to ${name}`).first()).toBeVisible();
    await mcp.waitForLoaded();
    // The first sign-in also fills the tool list.
    await expect(mcp.serverRow(name)).toContainText("1");
    const menu = await mcp.openActions(name);
    await expect(
      menu.getByRole("menuitem", { name: "Sign in again" })
    ).toBeVisible();
    // Nothing to change: each member signs in.
    await expect(
      menu.getByRole("menuitem", { name: "Change credential" })
    ).toHaveCount(0);
    await page.keyboard.press("Escape");

    // Sign out, then sign in from Chat: the round trip comes back to the
    // conversation, and the server is on.
    await mcp.runAction(name, "Sign out of this server");
    await page.goto("/chat?target=inst-mock");
    const tools = page.getByRole("group", { name: "Tools", exact: true });
    await expect(tools).toContainText("needs your sign-in");
    await tools.getByRole("button", { name: `Connect ${name}` }).click();
    await page
      .getByRole("dialog", { name: `Connect ${name}` })
      .getByRole("button", { name: `Sign in to ${name}` })
      .click();
    await expect(page).toHaveURL(/\/chat\?target=inst-mock$/);
    await expect(page.getByText(`Signed in to ${name}`).first()).toBeVisible();
    await expect(
      page.getByRole("switch", { name: `Use ${name}` })
    ).toBeChecked();

    await mcp.open();
    await mcp.waitForLoaded();
    await mcp.deleteServer(name);
  });

  test.describe("refusals", () => {
    test.use({ allowedConsoleErrors: [FAILED_RESOURCE] });

    test("the callback page shows what the authorization server said", async ({
      page,
    }) => {
      await page.goto(
        "/mcp-servers/oauth/callback?error=access_denied&error_description=The+user+said+no"
      );
      await expect(
        page.getByRole("alert").filter({ hasText: "no" })
      ).toHaveText("The user said no");
    });

    test("a state nobody started is refused", async ({ page }) => {
      await page.goto("/mcp-servers/oauth/callback?code=mock&state=nothing");
      await expect(
        page.getByRole("alert").filter({ hasText: /sign-in/i })
      ).toBeVisible();
      await expect(
        page.getByRole("link", { name: "Back to MCP servers" })
      ).toBeVisible();
    });
  });
});
