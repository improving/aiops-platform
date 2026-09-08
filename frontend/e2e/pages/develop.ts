import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

/** The Develop page: a Langflow iframe, or a "not configured" card. */
export class DevelopPage extends AppShell {
  readonly iframe: Locator;
  readonly notConfigured: Locator;
  /** The organization panel above the iframe (Langflow for <org>). */
  readonly panel: Locator;
  /** The panel's "Models (N)" button that opens the searchable picker. */
  readonly models: Locator;
  /** The picker's search box. */
  readonly modelSearch: Locator;

  constructor(page: Page) {
    super(page);
    this.iframe = page.locator("iframe");
    this.notConfigured = page.getByText("Langflow is not configured");
    this.panel = page.getByRole("region", { name: /Langflow for/ });
    this.models = this.panel.getByRole("combobox", { name: "Models" });
    this.modelSearch = page.getByPlaceholder("Search models");
  }

  /** One option of the open picker, by its model name. */
  modelOption(name: string): Locator {
    return this.page.getByRole("option", { name: new RegExp(name) });
  }

  async open() {
    await this.goto("/develop");
  }
}
