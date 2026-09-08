import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class TokensPage extends AppShell {
  readonly createButton: Locator;
  readonly table: Locator;
  readonly newToken: Locator;
  readonly doneButton: Locator;

  constructor(page: Page) {
    super(page);
    this.createButton = page.getByRole("button", { name: "Create token" });
    this.table = page.getByRole("table", { name: "API tokens" });
    this.newToken = page.getByTestId("new-token");
    this.doneButton = page.getByRole("button", { name: "Done" });
  }

  async open() {
    await this.goto("/settings/tokens");
  }

  tokenRow(name: string): Locator {
    return this.table.locator("tbody tr").filter({ hasText: name });
  }

  /** Fill the dialog and submit; the dialog then shows the token once. */
  async createToken(
    name: string,
    scope: "Read only" | "Read and write",
    expires: "30 days" | "90 days" | "365 days"
  ) {
    await this.createButton.click();
    const dialog = this.page.getByRole("dialog", { name: "Create token" });
    await dialog.getByRole("textbox", { name: "Name" }).fill(name);
    await dialog.getByRole("combobox", { name: "Scope" }).click();
    await this.page.getByRole("option", { name: scope }).click();
    await dialog.getByRole("combobox", { name: "Expires in" }).click();
    await this.page.getByRole("option", { name: expires }).click();
    await dialog.getByRole("button", { name: "Create", exact: true }).click();
    await this.newToken.waitFor();
  }

  /** The new token is masked; click the eye to read it off the page. */
  async revealNewToken() {
    await this.page
      .getByRole("button", { name: "Reveal API token" })
      .click();
  }

  async revoke(name: string) {
    await this.tokenRow(name).getByRole("button", { name: "Revoke" }).click();
    await this.confirmDelete();
  }
}
