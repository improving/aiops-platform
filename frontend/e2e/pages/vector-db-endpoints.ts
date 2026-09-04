import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class VectorDBEndpointsPage extends AppShell {
  readonly search: Locator;
  readonly cards: Locator;
  readonly emptyState: Locator;

  constructor(page: Page) {
    super(page);
    this.search = page.getByPlaceholder("Search by name...");
    this.cards = page.locator('main [data-slot="card"]');
    this.emptyState = page.getByText("No vector databases available.");
  }

  async open() {
    await this.goto("/vector-databases/endpoints");
  }

  /** The card for the instance with this id. */
  cardById(id: string): Locator {
    return this.cards.filter({ hasText: `ID: ${id}` });
  }

  deleteButton(card: Locator): Locator {
    return card.getByRole("button", { name: "Delete" });
  }
}
