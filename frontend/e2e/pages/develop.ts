import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

/** The Develop page: a Langflow iframe, or a "not configured" card. */
export class DevelopPage extends AppShell {
  readonly iframe: Locator;
  readonly notConfigured: Locator;

  constructor(page: Page) {
    super(page);
    this.iframe = page.locator("iframe");
    this.notConfigured = page.getByText("Langflow is not configured");
  }

  async open() {
    await this.goto("/develop");
  }
}
