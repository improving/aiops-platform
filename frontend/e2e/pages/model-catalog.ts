import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class ModelCatalogPage extends AppShell {
  readonly search: Locator;
  readonly categoryFilter: Locator;
  readonly subcategoryFilter: Locator;
  readonly manageRegistryLink: Locator;
  readonly cards: Locator;

  constructor(page: Page) {
    super(page);
    this.search = page.getByPlaceholder("Search by model name or ID");
    // The two shadcn Select triggers have no label; they are the only
    // comboboxes on the page, in DOM order.
    this.categoryFilter = page.getByRole("combobox").nth(0);
    this.subcategoryFilter = page.getByRole("combobox").nth(1);
    this.manageRegistryLink = page.getByRole("link", {
      name: "Manage registry",
    });
    this.cards = page.locator('main [data-slot="card"]');
  }

  async open() {
    await this.goto("/models/catalog");
  }

  /** The card whose title link is exactly `name`. */
  card(name: string): Locator {
    return this.cards.filter({
      has: this.page.getByRole("link", { name, exact: true }),
    });
  }

  /** Title links of every visible card, in order. */
  titleLinks(): Locator {
    return this.cards.locator('[data-slot="card-title"] a');
  }

  async selectCategory(option: string) {
    await this.categoryFilter.click();
    await this.page.getByRole("option", { name: option, exact: true }).click();
  }

  async selectSubcategory(option: string) {
    await this.subcategoryFilter.click();
    await this.page.getByRole("option", { name: option, exact: true }).click();
  }
}
