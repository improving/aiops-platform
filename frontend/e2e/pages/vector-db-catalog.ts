import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class VectorDBCatalogPage extends AppShell {
  readonly cards: Locator;

  constructor(page: Page) {
    super(page);
    this.cards = page.locator('main [data-slot="card"]');
  }

  async open() {
    await this.goto("/vector-databases/catalog");
  }

  card(name: string): Locator {
    return this.cards.filter({
      has: this.page.locator('[data-slot="card-title"]', {
        hasText: new RegExp(`^${name}$`),
      }),
    });
  }

  async launch(name: string) {
    await this.card(name).getByRole("button", { name: "Launch" }).click();
  }

  /** The create-instance dialog. */
  createDialog(): Locator {
    return this.dialog().filter({
      hasText: "Create Vector Database Instance",
    });
  }

  /** The service type select inside the dialog (ClusterIP / LoadBalancer). */
  serviceTypeSelect(): Locator {
    return this.createDialog().getByRole("combobox");
  }
}
