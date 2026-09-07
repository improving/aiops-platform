import { expect, type Locator, type Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export type InstanceTab = "Details" | "Logs" | "Events" | "Dashboards";
export type InstanceAction = "Restart" | "Stop" | "Resume" | "Scale…";

export class InferenceEndpointPage extends AppShell {
  readonly chatButton: Locator;
  readonly deleteButton: Locator;
  readonly actionsButton: Locator;
  readonly errorBanner: Locator;
  readonly logOutput: Locator;
  readonly containerSelect: Locator;
  readonly linesSelect: Locator;
  readonly eventsTable: Locator;

  constructor(page: Page) {
    super(page);
    // Scoped to main: the header also has a "Chat" link.
    this.chatButton = this.page
      .locator("main")
      .getByRole("link", { name: "Chat", exact: true });
    this.deleteButton = this.page
      .locator("main")
      .getByRole("button", { name: "Delete", exact: true });
    this.actionsButton = this.page
      .locator("main")
      .getByRole("button", { name: "Actions", exact: true });
    this.errorBanner = this.page.locator("main").getByRole("alert");
    this.logOutput = page.getByRole("group", { name: "Log output" });
    this.containerSelect = page.getByRole("combobox", { name: "Container" });
    this.linesSelect = page.getByRole("combobox", { name: "Lines" });
    this.eventsTable = page.getByRole("table", { name: "Events" });
  }

  async open(id: string) {
    await this.goto(`/models/endpoints/${id}`);
  }

  tab(name: InstanceTab): Locator {
    return this.page.getByRole("tab", { name, exact: true });
  }

  /** The value next to the "Status" label on the Details tab. */
  statusField(): Locator {
    return this.page
      .locator("main")
      .getByText("Status", { exact: true })
      .locator("xpath=following-sibling::*[1]");
  }

  /** Open the Actions menu, pick an item and confirm its dialog. */
  async runAction(item: InstanceAction, confirm: string) {
    await this.actionsButton.click();
    await this.page.getByRole("menuitem", { name: item, exact: true }).click();
    const dialog = this.dialog();
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: confirm, exact: true }).click();
    await expect(dialog).toBeHidden({ timeout: 60_000 });
  }

  /** Delete through the shared dialog and wait for the list redirect. */
  async deleteInstance(timeout: number) {
    await this.deleteButton.click();
    await this.confirmDelete(timeout);
    await this.page.waitForURL(/\/models\/endpoints$/, { timeout });
  }
}
