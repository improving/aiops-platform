import { test, expect, shortId, FAILED_RESOURCE } from "../fixtures";
import { McpServersPage } from "../pages/mcp-servers";

// The TEST_MODE backend runs with AIOPS_CHAT_MOCK=true: discover() answers
// one tool ("echo", read_only true) for any valid public https URL (no DNS
// lookup in mock mode); http:// and private addresses answer 400.
// createServer stores a real row, so every test uses a unique name and
// deletes it when done. Every scenario below that provokes a 4xx opts into
// allowedConsoleErrors: Chromium logs a non-2xx response as a console error.

test.describe("MCP servers page", () => {
  test("the header links to the page, empty state or list renders", async ({
    page,
  }) => {
    const mcp = new McpServersPage(page);
    await mcp.goto("/");
    await mcp.navLink("MCP").click();
    await expect(page).toHaveURL(/\/mcp-servers$/);
    await mcp.expectHeading("MCP servers");
    await mcp.waitForLoaded();
    await expect(mcp.connectClientButton).toBeVisible();
  });

  test("a member sees the row read-only", async ({ page, asUser }) => {
    const mcp = new McpServersPage(page);
    await mcp.open();
    await mcp.waitForLoaded();
    const name = `srv_${shortId()}`;
    await mcp.addServer({ name, url: "https://mcp.example.com/mcp" });
    await expect(mcp.serverRow(name)).toBeVisible();

    const ctx = await asUser("alice");
    const memberPage = await ctx.newPage();
    const memberMcp = new McpServersPage(memberPage);
    await memberMcp.open();
    await memberMcp.waitForLoaded();
    await expect(memberMcp.serverRow(name)).toBeVisible();
    await expect(memberMcp.headerAddButton).toHaveCount(0);

    const menu = await memberMcp.openActions(name);
    await expect(
      menu.getByRole("menuitem", { name: "Try in chat" })
    ).toBeVisible();
    await expect(
      menu.getByRole("menuitem", { name: "View tools" })
    ).toBeVisible();
    await expect(menu.getByRole("menuitem", { name: "Delete" })).toHaveCount(0);
    await memberPage.keyboard.press("Escape");

    await mcp.deleteServer(name);
  });

  test("Connect a client shows the endpoint and the Claude Code snippet", async ({
    page,
  }) => {
    const mcp = new McpServersPage(page);
    await mcp.open();
    await mcp.waitForLoaded();
    await mcp.connectClientButton.click();
    const dialog = page.getByRole("dialog", { name: "Connect a client" });
    await expect(dialog).toBeVisible();
    const endpointText = await dialog.locator("code").first().textContent();
    expect(endpointText).toMatch(/\/v1alpha1\/mcp$/);
    await expect(
      dialog.getByRole("group", { name: "Claude Code example" })
    ).toContainText("claude mcp add --transport http aiops");
  });
});

test.describe("MCP servers page, writes that provoke a 4xx", () => {
  test.use({ allowedConsoleErrors: [FAILED_RESOURCE] });

  test("admin adds a server, edits its tools, disables and deletes it", async ({
    page,
  }) => {
    test.slow();
    const mcp = new McpServersPage(page);
    await mcp.open();
    await mcp.waitForLoaded();

    // A refused URL shows the inline alert on step 1 and stays on step 1.
    await mcp.openAddDialog();
    const name = `srv_${shortId()}`;
    await mcp.fillConnection({ name, url: "http://example.com/mcp" });
    await mcp.testConnection();
    await expect(mcp.connectionAlert()).toBeVisible();
    await expect(
      page.getByRole("dialog", { name: "Add MCP server" })
    ).toContainText("Step 1 of 2");

    // A valid URL connects and lists the mock's one tool.
    const urlBox = page
      .getByRole("dialog", { name: "Add MCP server" })
      .getByRole("textbox", { name: "Server URL" });
    await urlBox.fill("");
    await urlBox.fill("https://mcp.example.com/mcp");
    await mcp.testConnection();
    await expect(
      page.getByRole("dialog", { name: "Add MCP server" })
    ).toContainText("Connected · 1 tools found");
    await expect(page.getByText("echo")).toBeVisible();

    await mcp.finishAdd(["echo"]);

    await expect(mcp.serverRow(name)).toBeVisible();
    await expect(mcp.serverRow(name)).toContainText("mcp.example.com/mcp");
    await expect(mcp.serverRow(name)).toContainText("Connected");

    // Edit tools shows the allowed tool.
    await mcp.runAction(name, "Edit tools");
    const editDialog = page.getByRole("dialog", { name: "Edit tools" });
    await expect(editDialog.getByText("echo")).toBeVisible();
    await editDialog.getByRole("button", { name: "Cancel" }).click();

    // Disable turns the status to Disabled.
    await mcp.runAction(name, "Disable");
    await expect(mcp.serverRow(name)).toContainText("Disabled");
    await mcp.runAction(name, "Enable");
    await expect(mcp.serverRow(name)).toContainText("Connected");

    // Delete removes the row.
    await mcp.deleteServer(name);
    await expect(mcp.serverRow(name)).toHaveCount(0);
  });

  test("a duplicate name shows the 409 detail inline on step 2", async ({
    page,
  }) => {
    test.slow();
    const mcp = new McpServersPage(page);
    await mcp.open();
    await mcp.waitForLoaded();

    const name = `srv_${shortId()}`;
    await mcp.addServer({ name, url: "https://mcp.example.com/mcp" });
    await expect(mcp.serverRow(name)).toBeVisible();

    await mcp.openAddDialog();
    await mcp.fillConnection({ name, url: "https://mcp.example.com/mcp" });
    await mcp.testConnection();
    const dialog = page.getByRole("dialog", { name: "Add MCP server" });
    await expect(dialog).toContainText("Connected · 1 tools found");
    await dialog.getByRole("button", { name: "Add server" }).click();
    await expect(mcp.connectionAlert()).toBeVisible();
    await dialog.getByRole("button", { name: "Back" }).click();
    await dialog.getByRole("button", { name: "Cancel" }).click();

    await mcp.deleteServer(name);
  });

  test("a private URL is refused with a 400", async ({ page }) => {
    const mcp = new McpServersPage(page);
    await mcp.open();
    await mcp.waitForLoaded();
    await mcp.openAddDialog();
    await mcp.fillConnection({
      name: `srv_${shortId()}`,
      url: "http://localhost/mcp",
    });
    await mcp.testConnection();
    await expect(mcp.connectionAlert()).toBeVisible();
    await page
      .getByRole("dialog", { name: "Add MCP server" })
      .getByRole("button", { name: "Cancel" })
      .click();
  });
});

test.describe("MCP servers page, day-two actions of an admin", () => {
  test("limits the tools, refreshes them, and changes the shared credential", async ({
    page,
  }) => {
    test.slow();
    const name = `ops_${Math.random().toString(36).slice(2, 10)}`;
    const created = await page.request.post("/api/v1alpha1/mcp/servers", {
      data: {
        name,
        url: "https://mcp.example.com/mcp",
        credential: { auth_type: "bearer", value: "first" },
      },
    });
    expect(created.status()).toBe(201);
    const id = (await created.json()).id;
    const read = async () =>
      (await (await page.request.get("/api/v1alpha1/mcp/servers")).json()).find(
        (s: { id: string }) => s.id === id
      );

    const mcp = new McpServersPage(page);
    await mcp.open();
    await mcp.waitForLoaded();
    await expect(mcp.serverRow(name)).toContainText("Connected");

    // Edit tools, the save path: from "all tools" to a selection.
    await mcp.runAction(name, "Edit tools");
    const edit = page.getByRole("dialog", { name: "Edit tools" });
    await edit.getByRole("radio", { name: "Only the selected tools" }).check();
    await expect(edit.getByRole("checkbox", { name: "echo" })).toBeChecked();
    await edit.getByRole("button", { name: "Save" }).click();
    await expect(edit).toBeHidden();
    expect((await read()).allowed_tools).toEqual(["echo"]);
    await expect(mcp.serverRow(name)).toContainText("1 / 1");

    // Refresh tools keeps the row and says so.
    await mcp.runAction(name, "Refresh tools");
    await expect(page.getByText("Tools refreshed").first()).toBeVisible();
    await expect(mcp.serverRow(name)).toContainText("Connected");

    // Change credential on a shared server: no warning, the mode stays.
    const before = (await read()).credential_set_at;
    await mcp.runAction(name, "Change credential");
    const change = page.getByRole("dialog", { name: "Change credential" });
    await expect(change.getByRole("alert")).toHaveCount(0);
    await change.getByRole("radio", { name: "Bearer token" }).check();
    await change.getByLabel("Token", { exact: true }).fill("second");
    await change.getByRole("button", { name: "Save" }).click();
    await expect(change).toBeHidden();
    const after = await read();
    expect(after.credential_mode).toBe("shared");
    expect(after.credential_set_at).not.toBe(before);

    // Remove credential: the server has none afterwards.
    await mcp.runAction(name, "Change credential");
    await change.getByRole("radio", { name: /Remove credential/ }).check();
    await change.getByRole("button", { name: "Save" }).click();
    await expect(change).toBeHidden();
    expect((await read()).credential_mode).toBe("none");

    await mcp.deleteServer(name);
  });
});

test.describe("an MCP server where each member brings their own credential", () => {
  test("the admin sets it up, and a member connects and disconnects theirs", async ({
    page,
    asUser,
  }) => {
    test.slow();
    const name = `own_${Math.random().toString(36).slice(2, 10)}`;
    const mcp = new McpServersPage(page);
    await mcp.open();
    await mcp.waitForLoaded();
    await mcp.openAddDialog();
    const dialog = page.getByRole("dialog", { name: "Add MCP server" });
    await dialog.getByLabel("Name", { exact: true }).fill(name);
    await dialog.getByLabel("Server URL").fill("https://mcp.example.com/mcp");
    await dialog.getByRole("radio", { name: "Bearer token" }).check();
    await dialog.getByLabel("Token", { exact: true }).fill("admin-token");
    await dialog
      .getByRole("radio", { name: "Each member brings their own" })
      .check();
    await dialog
      .getByLabel("Where to get a credential")
      .fill("https://github.com/settings/tokens");
    await dialog.getByRole("button", { name: "Test connection" }).click();
    await expect(dialog).toContainText("with that member's own credential");
    await dialog.getByRole("button", { name: "Add server" }).click();
    await expect(mcp.serverRow(name)).toBeVisible();

    // A member: not connected yet, in the page and in Chat.
    const ctx = await asUser("alice");
    const alice = await ctx.newPage();
    const theirs = new McpServersPage(alice);
    await theirs.open();
    await theirs.waitForLoaded();
    await theirs.runAction(name, "Connect my credential");
    const connect = alice.getByRole("dialog", { name: `Connect ${name}` });
    await expect(
      connect.getByRole("link", { name: "Where to get one" })
    ).toHaveAttribute("href", "https://github.com/settings/tokens");
    await connect.getByLabel("Personal access token").fill("alice-token");
    await connect.getByRole("button", { name: "Test and save" }).click();
    await expect(connect).toBeHidden();
    await theirs.runAction(name, "Disconnect my credential");

    await alice.goto("/chat?target=inst-mock");
    const tools = alice.getByRole("group", { name: "Tools" });
    await expect(tools).toContainText("needs your credential");
    await expect(
      tools.getByRole("switch", { name: `Use ${name}` })
    ).toBeDisabled();
    await tools.getByRole("button", { name: `Connect ${name}` }).click();
    const inChat = alice.getByRole("dialog", { name: `Connect ${name}` });
    await inChat.getByLabel("Personal access token").fill("alice-token");
    await inChat.getByRole("button", { name: "Test and save" }).click();
    // Connected in order to use it: it is on.
    await expect(
      tools.getByRole("switch", { name: `Use ${name}` })
    ).toBeChecked();
    await expect(alice.getByTestId("chat-tools-on")).toContainText(
      "1 tool server on"
    );
    await tools.getByRole("switch", { name: `Use ${name}` }).click();

    // "Change credential" on this server replaces every member's own:
    // it says so, and Save waits for the admin to say so too.
    await mcp.runAction(name, "Change credential");
    const change = page.getByRole("dialog", { name: "Change credential" });
    await expect(change.getByRole("alert")).toContainText(
      "every member's credential is deleted"
    );
    await change.getByRole("radio", { name: "Bearer token" }).check();
    await change.getByLabel("Token", { exact: true }).fill("one-for-all");
    const save = change.getByRole("button", { name: "Save" });
    await expect(save).toBeDisabled();
    await change
      .getByRole("checkbox", { name: "Delete every member's credential" })
      .check();
    await save.click();
    await expect(change).toBeHidden();
    await alice.reload();
    await expect(alice.getByRole("group", { name: "Tools" })).not.toContainText(
      "needs your credential"
    );

    await mcp.deleteServer(name);
  });
});
