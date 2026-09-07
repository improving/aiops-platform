import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class AuditPage extends AppShell {
  readonly table: Locator;
  readonly applyButton: Locator;
  readonly exportButton: Locator;
  readonly actionSelect: Locator;

  constructor(page: Page) {
    super(page);
    this.table = page.getByRole("table", { name: "Audit events" });
    this.applyButton = page.getByRole("button", { name: "Apply" });
    this.exportButton = page.getByRole("button", { name: "Export CSV" });
    this.actionSelect = page.getByRole("combobox", { name: "Action" });
  }

  async open() {
    await this.goto("/audit");
  }

  rows(): Locator {
    return this.table.locator("tbody tr");
  }

  async selectAction(label: string) {
    await this.actionSelect.click();
    await this.page.getByRole("option", { name: label, exact: true }).click();
  }
}
