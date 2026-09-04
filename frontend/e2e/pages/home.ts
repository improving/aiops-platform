import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class HomePage extends AppShell {
  readonly cards: Locator;

  constructor(page: Page) {
    super(page);
    this.cards = page.locator('main [data-slot="card"]');
  }

  async open() {
    await this.goto("/");
  }

  /** The card whose title is exactly `title`. */
  card(title: string): Locator {
    return this.cards.filter({
      has: this.page.locator('[data-slot="card-title"]', {
        hasText: new RegExp(`^${title}$`),
      }),
    });
  }

  cardLink(title: string, text: string): Locator {
    return this.card(title).getByRole("link", { name: text, exact: true });
  }
}
