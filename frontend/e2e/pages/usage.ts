import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class UsagePage extends AppShell {
  readonly periodSelect: Locator;
  readonly byTargetTable: Locator;
  readonly byUserTable: Locator;
  readonly requestsTotal: Locator;
  readonly promptTokensTotal: Locator;
  readonly completionTokensTotal: Locator;
  readonly spendTotal: Locator;
  readonly downloadButton: Locator;

  constructor(page: Page) {
    super(page);
    this.periodSelect = page.getByRole("combobox", { name: "Period" });
    this.downloadButton = page.getByRole("button", { name: "Download CSV" });
    this.byTargetTable = page.getByRole("table", { name: "By target" });
    this.byUserTable = page.getByRole("table", { name: "By user and day" });
    this.requestsTotal = page.getByTestId("usage-total-requests");
    this.promptTokensTotal = page.getByTestId("usage-total-prompt-tokens");
    this.completionTokensTotal = page.getByTestId(
      "usage-total-completion-tokens"
    );
    this.spendTotal = page.getByTestId("usage-total-spend");
  }

  async open() {
    await this.goto("/usage");
  }

  async selectPeriod(label: string) {
    await this.periodSelect.click();
    await this.page.getByRole("option", { name: label }).click();
  }
}
