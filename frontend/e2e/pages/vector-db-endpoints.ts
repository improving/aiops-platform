import { expect, type Locator, type Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class VectorDBEndpointsPage extends AppShell {
  readonly search: Locator;
  readonly cards: Locator;
  readonly emptyState: Locator;

  constructor(page: Page) {
    super(page);
    this.search = page.getByPlaceholder("Search by name...");
    this.cards = page.locator('main [data-slot="card"]');
    this.emptyState = page.getByText("No vector database instances yet.");
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

  showCredentialButton(card: Locator): Locator {
    return card.getByRole("button", { name: "Show credential" });
  }

  /** The "API key for <name>" dialog ShowCredentialButton opens. */
  credentialDialog(): Locator {
    return this.dialog().filter({ hasText: "API key for" });
  }

  /**
   * Click "Show credential" on the card and return the dialog once it is
   * open. The key value (when the backend still hands it out) is the code
   * element labelled "API key value".
   */
  async revealCredential(card: Locator): Promise<Locator> {
    await this.showCredentialButton(card).click();
    const dialog = this.credentialDialog();
    await expect(dialog).toBeVisible();
    return dialog;
  }

  credentialValue(dialog: Locator): Locator {
    return dialog.getByLabel("API key value", { exact: true });
  }

  async closeCredentialDialog(dialog: Locator) {
    // The footer button; the dialog's corner "X" is also named "Close".
    await dialog.getByRole("button", { name: "Close" }).first().click();
    await expect(dialog).toBeHidden();
  }
}
