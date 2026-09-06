import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class NotebookListPage extends AppShell {
  readonly cards: Locator;
  readonly emptyState: Locator;
  readonly newNotebookLink: Locator;

  constructor(page: Page) {
    super(page);
    this.cards = page.locator('main [data-slot="card"]');
    this.emptyState = page.getByText("No notebooks yet.");
    this.newNotebookLink = page.getByRole("link", { name: "New Notebook" });
  }

  async open() {
    await this.goto("/notebooks");
  }

  /** The title link of the notebook with this name. */
  notebookLink(name: string): Locator {
    return this.cards.getByRole("link", { name, exact: true });
  }
}

export class NotebookDetailsPage extends AppShell {
  readonly connectButton: Locator;
  readonly deleteButton: Locator;
  readonly notFound: Locator;

  constructor(page: Page) {
    super(page);
    this.connectButton = page.getByRole("button", { name: "Connect" });
    this.deleteButton = page.getByRole("button", { name: "Delete" });
    this.notFound = page.locator("main").getByText("Notebook not found", { exact: true });
  }

  async open(id: string) {
    await this.goto(`/notebooks/${id}`);
  }

  /** The value shown next to a "Label:" in the details grid. */
  field(label: string): Locator {
    return this.page
      .getByText(`${label}:`, { exact: true })
      .locator("xpath=following-sibling::span[1]");
  }
}
