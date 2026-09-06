import { expect, type Locator, type Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class VectorDBEndpointsPage extends AppShell {
  readonly search: Locator;
  readonly cards: Locator;
  readonly emptyState: Locator;
  readonly noMatch: Locator;
  readonly showMore: Locator;
  readonly launchButton: Locator;

  constructor(page: Page) {
    super(page);
    this.search = page.getByPlaceholder("Search by name...");
    this.cards = page.locator('main [data-slot="card"]');
    this.emptyState = page.getByText("No vector database instances yet.");
    this.noMatch = page.getByText("No instances match.", { exact: true });
    this.showMore = page.getByRole("button", { name: /Show more/ });
    this.launchButton = page.getByRole("button", { name: "Launch" });
  }

  async open() {
    await this.goto("/vector-databases/endpoints");
  }

  async filterStatus(label: "All" | "Ready" | "Not ready") {
    await this.page.getByRole("combobox", { name: "Status" }).click();
    await this.page.getByRole("option", { name: label, exact: true }).click();
  }

  async sortBy(label: "Name A-Z" | "Name Z-A" | "Status") {
    await this.page.getByRole("combobox", { name: "Sort" }).click();
    await this.page.getByRole("option", { name: label, exact: true }).click();
  }

  /** The card for the instance with this id. */
  cardById(id: string): Locator {
    return this.cards.filter({ hasText: `ID: ${id}` });
  }

  /** The title link of the instance card, which opens the detail page. */
  detailsLink(card: Locator): Locator {
    return card.getByRole("link").first();
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

export class VectorDBInstanceDetailsPage extends AppShell {
  readonly notFound: Locator;
  readonly deleteButton: Locator;
  readonly showCredentialButton: Locator;
  readonly curlExample: Locator;

  constructor(page: Page) {
    super(page);
    // Scoped to main and exact: the 404 toast repeats the same words.
    this.notFound = page
      .locator("main")
      .getByText("Vector database instance not found", { exact: true });
    this.deleteButton = page
      .locator("main")
      .getByRole("button", { name: "Delete", exact: true });
    this.showCredentialButton = page
      .locator("main")
      .getByRole("button", { name: "Show credential" });
    this.curlExample = page.getByRole("group", { name: "curl example" });
  }

  async open(id: string) {
    await this.goto(`/vector-databases/endpoints/${id}`);
  }

  /** The value shown next to a "Label" in the details grid. */
  field(label: string): Locator {
    return this.page
      .getByText(label, { exact: true })
      .locator("xpath=following-sibling::*[1]");
  }

  /** A copy button by its plain (non-compound) label, as used on this page. */
  copyButton(label: string): Locator {
    return this.page.getByRole("button", { name: `Copy ${label}` });
  }
}
