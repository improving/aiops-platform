import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class InferenceEndpointPage extends AppShell {
  readonly chatButton: Locator;
  readonly deleteButton: Locator;

  constructor(page: Page) {
    super(page);
    // Scoped to main: the header also has a "Chat" link.
    this.chatButton = this.page
      .locator("main")
      .getByRole("link", { name: "Chat", exact: true });
    this.deleteButton = this.page
      .locator("main")
      .getByRole("button", { name: "Delete", exact: true });
  }

  async open(id: string) {
    await this.goto(`/models/endpoints/${id}`);
  }

  /** Delete through the shared dialog and wait for the list redirect. */
  async deleteInstance(timeout: number) {
    await this.deleteButton.click();
    await this.confirmDelete(timeout);
    await this.page.waitForURL(/\/models\/endpoints$/, { timeout });
  }
}
