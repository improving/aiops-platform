import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class McpServersPage extends AppShell {
  readonly connectClientButton: Locator;
  readonly headerAddButton: Locator;
  readonly emptyStateAddButton: Locator;
  readonly table: Locator;

  constructor(page: Page) {
    super(page);
    this.connectClientButton = page.getByRole("button", {
      name: "Connect a client",
    });
    this.headerAddButton = page.getByRole("button", {
      name: "Add MCP server",
      exact: true,
    });
    this.emptyStateAddButton = page.getByRole("button", {
      name: "+ Add MCP server",
    });
    this.table = page.getByRole("table", { name: "MCP servers" });
  }

  async open() {
    await this.goto("/mcp-servers");
  }

  /** Whichever "add" affordance is on screen right now (empty state or the
      list header); both open the same dialog. */
  async openAddDialog() {
    if (await this.emptyStateAddButton.isVisible().catch(() => false)) {
      await this.emptyStateAddButton.click();
    } else {
      await this.headerAddButton.click();
      await this.chooseFromAddMenu("Connect a remote server");
    }
    await this.page.getByRole("dialog", { name: "Add MCP server" }).waitFor();
  }

  /** For an organization admin the header button is a menu (connect or
      deploy); for every other writer it opens the add dialog at once. */
  private async chooseFromAddMenu(item: string) {
    const entry = this.page.getByRole("menuitem", { name: item });
    const dialog = this.page.getByRole("dialog");
    await entry.or(dialog).first().waitFor();
    if (await entry.isVisible()) await entry.click();
  }

  async openDeployDialog() {
    const emptyDeploy = this.page.getByRole("button", {
      name: "Deploy from the catalog",
    });
    if (await emptyDeploy.isVisible().catch(() => false)) {
      await emptyDeploy.click();
    } else {
      await this.headerAddButton.click();
      await this.page
        .getByRole("menuitem", { name: "Deploy from the catalog" })
        .click();
    }
    const dialog = this.page.getByRole("dialog", {
      name: "Deploy an MCP server",
    });
    await dialog.waitFor();
    return dialog;
  }

  async openTryOne(label: "DeepWiki" | "Context7") {
    await this.page.getByRole("button", { name: label }).click();
    await this.page.getByRole("dialog", { name: "Add MCP server" }).waitFor();
  }

  serverRow(name: string): Locator {
    return this.page.getByRole("row", { name, exact: true });
  }

  actionsButton(name: string): Locator {
    return this.page.getByRole("button", { name: `Actions for ${name}` });
  }

  async openActions(name: string) {
    // A menu that an item just closed is still in the DOM while it
    // animates out; a click on the trigger in that moment opens a menu
    // that the old one's focus return closes again.
    await this.page.getByRole("menu").waitFor({ state: "detached" });
    await this.actionsButton(name).click();
    const menu = this.page.getByRole("menu");
    await menu.waitFor();
    return menu;
  }

  async runAction(name: string, action: string) {
    const menu = await this.openActions(name);
    await menu.getByRole("menuitem", { name: action }).click();
  }

  /**
   * Fill step 1 (Name, Server URL, optional Authentication) and click
   * "Test connection". Leaves the dialog open so the caller can assert the
   * inline error, or `finishAdd` to complete step 2.
   */
  async fillConnection(options: { name: string; url: string }) {
    const dialog = this.page.getByRole("dialog", { name: "Add MCP server" });
    await dialog
      .getByRole("textbox", { name: "Name", exact: true })
      .fill(options.name);
    const urlBox = dialog.getByRole("textbox", { name: "Server URL" });
    await urlBox.fill("");
    await urlBox.fill(options.url);
  }

  async testConnection() {
    const dialog = this.page.getByRole("dialog", { name: "Add MCP server" });
    await dialog.getByRole("button", { name: "Test connection" }).click();
  }

  connectionAlert(): Locator {
    return this.page
      .getByRole("dialog", { name: "Add MCP server" })
      .getByRole("alert");
  }

  /** Step 2: pick "Only the selected tools" and check exactly `tools`,
      then submit. Pass no `tools` to keep "All tools, also new ones". */
  async finishAdd(tools?: string[]) {
    const dialog = this.page.getByRole("dialog", { name: "Add MCP server" });
    if (tools) {
      await dialog
        .getByRole("radio", { name: "Only the selected tools" })
        .check();
      const checkboxes = dialog.locator('[id^="mcp-add-tool-"]');
      const count = await checkboxes.count();
      for (let i = 0; i < count; i += 1) {
        const checkbox = checkboxes.nth(i);
        const id = (await checkbox.getAttribute("id"))!.replace(
          "mcp-add-tool-",
          ""
        );
        const shouldCheck = tools.includes(id);
        if ((await checkbox.isChecked()) !== shouldCheck) {
          if (shouldCheck) await checkbox.check();
          else await checkbox.uncheck();
        }
      }
    }
    await dialog.getByRole("button", { name: "Add server" }).click();
    await dialog.waitFor({ state: "hidden" });
  }

  /** Connect through the whole two-step flow in one call. */
  async addServer(options: { name: string; url: string; tools?: string[] }) {
    await this.openAddDialog();
    await this.fillConnection(options);
    await this.testConnection();
    await this.finishAdd(options.tools);
  }

  async deleteServer(name: string) {
    await this.runAction(name, "Delete");
    await this.confirmDelete();
  }
}
