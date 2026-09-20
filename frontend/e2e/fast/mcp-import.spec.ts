import { test, expect, shortId } from "../fixtures";
import { McpServersPage } from "../pages/mcp-servers";

// Import from the official MCP registry. With AIOPS_CHAT_MOCK the backend
// searches its recorded entries (backend/test_fixtures/mcp_registry.json),
// so the names below are real registry names, and nothing calls the network.

test.describe("import an MCP server from the registry", () => {
  test("a search result fills the connection form, and the rest is the usual path", async ({
    page,
  }) => {
    const mcp = new McpServersPage(page);
    await mcp.open();
    await mcp.waitForLoaded();
    await mcp.openAddDialog();
    const dialog = page.getByRole("dialog", { name: "Add MCP server" });

    await dialog.getByRole("tab", { name: "From the MCP registry" }).click();
    // Nothing to test while the search is open.
    await expect(
      dialog.getByRole("button", { name: "Test connection" })
    ).toHaveCount(0);
    await dialog.getByLabel("Search the MCP registry").fill("audiopod");
    await dialog.getByRole("button", { name: "Search" }).click();
    const entries = dialog.getByRole("list", { name: "Registry entries" });
    await expect(entries).toContainText("ai.audiopod/audiopod");
    await expect(dialog).toContainText("The platform has not reviewed them");
    await dialog
      .getByRole("button", { name: "Use ai.audiopod/audiopod" })
      .click();

    // Back on the form, filled: name, URL and the shape of the credential.
    await expect(
      dialog.getByRole("textbox", { name: "Name", exact: true })
    ).toHaveValue("audiopod");
    await expect(
      dialog.getByRole("textbox", { name: "Server URL" })
    ).toHaveValue("https://mcp.audiopod.ai");
    await expect(dialog.getByLabel("Custom header")).toBeChecked();
    await expect(dialog.getByLabel("Header name")).toHaveValue("X-API-Key");

    // The name is a suggestion; the connection test and the save are as ever.
    const name = `imp_${shortId()}`;
    await dialog.getByRole("textbox", { name: "Name", exact: true }).fill(name);
    await dialog.getByLabel("Header value").fill("a-key");
    await mcp.testConnection();
    await mcp.finishAdd();
    await expect(mcp.serverRow(name)).toBeVisible();
    await mcp.deleteServer(name);
  });

  test("an entry that cannot fill the form says why", async ({ page }) => {
    const mcp = new McpServersPage(page);
    await mcp.open();
    await mcp.waitForLoaded();
    await mcp.openAddDialog();
    const dialog = page.getByRole("dialog", { name: "Add MCP server" });
    await dialog.getByRole("tab", { name: "From the MCP registry" }).click();
    await dialog.getByLabel("Search the MCP registry").fill("ai.");
    await dialog.getByRole("button", { name: "Search" }).click();
    const entries = dialog.getByRole("list", { name: "Registry entries" });
    // A URL with placeholders, docker options, and an image to deploy.
    await expect(entries).toContainText("The URL needs values of yours");
    await expect(entries).toContainText("a platform admin imports it");
    await expect(
      dialog.getByRole("button", { name: "Use ai.autorfp/mcp" })
    ).toHaveCount(0);
  });

  test("with import turned off there is no tab", async ({ page }) => {
    await page.route("**/api/v1alpha1/config/ui", (route) =>
      route.fulfill({
        json: {
          grafanaUrl: "",
          langflowUrl: "",
          jaegerUrl: "",
          authMode: "disabled",
          mcpRegistry: false,
        },
      })
    );
    const mcp = new McpServersPage(page);
    await mcp.open();
    await mcp.waitForLoaded();
    await mcp.openAddDialog();
    const dialog = page.getByRole("dialog", { name: "Add MCP server" });
    await expect(
      dialog.getByRole("textbox", { name: "Name", exact: true })
    ).toBeVisible();
    await expect(dialog.getByRole("tab")).toHaveCount(0);
  });
});
