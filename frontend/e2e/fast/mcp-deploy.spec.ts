import { test, expect, shortId } from "../fixtures";
import { McpServersPage } from "../pages/mcp-servers";

// MCP servers the platform deploys. With AIOPS_CHAT_MOCK the backend
// installs nothing: a deployed server reads "Starting" for a few seconds
// and then runs by itself with the mock tool; one whose name starts with
// "failing" fails. Logs and events need a cluster, so they are stubbed.

test.describe("deploy an MCP server from the catalog", () => {
  test("an admin deploys Grafana, watches it start, and changes its settings", async ({
    page,
  }) => {
    await page.route("**/api/v1alpha1/mcp/instances/*/logs*", (route) =>
      route.fulfill({
        json: {
          pods: [
            {
              name: "mcpi-1",
              containers: [{ name: "mcp", log: "Starting Grafana MCP server" }],
            },
          ],
        },
      })
    );
    const mcp = new McpServersPage(page);
    await mcp.open();
    await mcp.waitForLoaded();
    const name = `graf_${shortId()}`;

    const dialog = await mcp.openDeployDialog();
    await expect(dialog.getByRole("list", { name: "Catalog" })).toContainText(
      "Grafana"
    );
    await dialog.getByRole("button", { name: "Choose Grafana" }).click();
    await dialog.getByLabel("Name", { exact: true }).fill(name);
    // A required setting is missing: nothing to deploy yet.
    await expect(dialog.getByRole("button", { name: "Deploy" })).toBeDisabled();
    await dialog
      .getByLabel("Grafana URL *")
      .fill("http://grafana.monitoring.svc:3000");
    await dialog.getByLabel("Service account token").fill("glsa_test");
    await expect(
      dialog.getByLabel(
        "Read only (the server offers no tools that change data)"
      )
    ).toBeChecked();
    await dialog.getByRole("button", { name: "Deploy" }).click();
    await expect(dialog).toBeHidden();

    // The row starts by itself, and the page follows it with no reload.
    const row = mcp.serverRow(name);
    await expect(row).toContainText("deployed");
    await expect(row).toContainText("runs on the platform");
    await expect(row).toContainText("Starting");
    await expect(row).toContainText("Connected", { timeout: 20_000 });

    // The platform runs it: no credential to change, settings to edit.
    const menu = await mcp.openActions(name);
    await expect(
      menu.getByRole("menuitem", { name: "Change credential" })
    ).toHaveCount(0);
    await menu.getByRole("menuitem", { name: "Edit settings" }).click();
    const sheet = page.getByRole("dialog", { name });
    await expect(sheet.getByLabel("Grafana URL *")).toHaveValue(
      "http://grafana.monitoring.svc:3000"
    );
    // A secret is never shown again; empty keeps it.
    await expect(sheet.getByLabel("Service account token")).toHaveValue("");
    await expect(sheet.getByLabel("Service account token")).toHaveAttribute(
      "placeholder",
      "set; leave empty to keep it"
    );
    await sheet
      .getByLabel("Grafana URL *")
      .fill("http://grafana.other.svc:3000");
    await sheet.getByRole("button", { name: "Save settings" }).click();
    await expect(
      page.getByText("Saved; the server restarts").first()
    ).toBeVisible();
    await sheet.getByRole("tab", { name: "Logs" }).click();
    await expect(sheet).toContainText("Starting Grafana MCP server");
    await page.keyboard.press("Escape");

    await mcp.deleteServer(name);
  });

  test("a server that fails says why, and can be deleted", async ({ page }) => {
    const mcp = new McpServersPage(page);
    await mcp.open();
    await mcp.waitForLoaded();
    const name = `failing_${shortId()}`;
    const dialog = await mcp.openDeployDialog();
    await dialog.getByRole("button", { name: "Choose Grafana" }).click();
    await dialog.getByLabel("Name", { exact: true }).fill(name);
    await dialog.getByLabel("Grafana URL *").fill("http://grafana:3000");
    await dialog.getByRole("button", { name: "Deploy" }).click();
    const row = mcp.serverRow(name);
    await expect(row).toContainText("Failed", { timeout: 20_000 });
    await expect(row).toContainText("ImagePullBackOff");
    await mcp.deleteServer(name);
  });

  test("a member cannot deploy, and a starting server is off in Chat", async ({
    page,
    asUser,
  }) => {
    const mcp = new McpServersPage(page);
    await mcp.open();
    await mcp.waitForLoaded();
    const name = `slow_${shortId()}`;
    const dialog = await mcp.openDeployDialog();
    await dialog.getByRole("button", { name: "Choose Grafana" }).click();
    await dialog.getByLabel("Name", { exact: true }).fill(name);
    await dialog.getByLabel("Grafana URL *").fill("http://grafana:3000");
    await dialog.getByRole("button", { name: "Deploy" }).click();
    await expect(mcp.serverRow(name)).toContainText("Starting");

    const ctx = await asUser("alice");
    const memberPage = await ctx.newPage();
    const member = new McpServersPage(memberPage);
    await member.open();
    await member.waitForLoaded();
    await expect(member.serverRow(name)).toBeVisible();
    // A member adds a remote server for themselves: a plain button, no menu.
    await member.headerAddButton.click();
    await expect(
      memberPage.getByRole("dialog", { name: "Add MCP server" })
    ).toBeVisible();
    await expect(
      memberPage.getByRole("menuitem", { name: "Deploy from the catalog" })
    ).toHaveCount(0);

    await expect(mcp.serverRow(name)).toContainText("Connected", {
      timeout: 20_000,
    });
    await mcp.deleteServer(name);
  });
});

test.describe("the deploy catalog of a platform admin", () => {
  // Two users, two pages and a reload: more than the default minute on a
  // slow runner.
  test.setTimeout(150_000);

  // An attempt that stopped half-way leaves its entry in the catalog, and
  // the retry would find "Imported" where it wants to import.
  test.beforeEach(async ({ page }) => {
    const listed = await page.request.get("/api/v1alpha1/mcp/catalog");
    for (const entry of (await listed.json()) as {
      id: string;
      source: string;
    }[]) {
      if (entry.source !== "builtin")
        await page.request.delete(`/api/v1alpha1/mcp/catalog/${entry.id}`);
    }
  });

  test("imports an image entry as a draft, reviews and publishes it", async ({
    page,
    asUser,
  }) => {
    const mcp = new McpServersPage(page);
    await mcp.open();
    await mcp.waitForLoaded();
    const dialog = await mcp.openDeployDialog();
    await dialog.getByLabel("Search images in the registry").fill("ai.");
    await dialog.getByRole("button", { name: "Search" }).click();
    const images = dialog.getByRole("list", { name: "Registry images" });
    // What the chart cannot run is refused with the reason.
    await expect(images).toContainText("Needs docker run options");
    await dialog
      .getByRole("button", { name: "Import ai.midplane/midplane" })
      .click();

    const review = page.getByRole("dialog", { name: /^Review/ });
    await expect(review).toContainText("docker.io/midplane/midplane:0.20.0");
    await expect(review).toContainText("DATABASE_URL · secret · required");
    await expect(review.getByLabel("The internet (port 443)")).toBeChecked();

    // A draft is invisible to an organization admin.
    const ctx = await asUser("orgadmin");
    const adminPage = await ctx.newPage();
    const orgAdmin = new McpServersPage(adminPage);
    await orgAdmin.open();
    await orgAdmin.waitForLoaded();
    let theirs = await orgAdmin.openDeployDialog();
    await expect(theirs.getByRole("list", { name: "Catalog" })).toContainText(
      "Grafana"
    );
    await expect(theirs).not.toContainText("midplane");
    await expect(theirs).not.toContainText("Import from the MCP registry");
    await adminPage.keyboard.press("Escape");

    await review.getByRole("button", { name: "Publish" }).click();
    await expect(review).toBeHidden();
    await adminPage.reload();
    await orgAdmin.waitForLoaded();
    theirs = await orgAdmin.openDeployDialog();
    await expect(
      theirs.getByRole("button", { name: "Choose midplane" })
    ).toBeVisible();

    // Clean up: the entry goes, so the next run can import it again.
    await dialog.getByRole("button", { name: "Review midplane" }).click();
    await page
      .getByRole("dialog", { name: /^Review/ })
      .getByRole("button", { name: "Remove" })
      .click();
    await expect(
      dialog.getByRole("list", { name: "Catalog" })
    ).not.toContainText("midplane");
  });
});
