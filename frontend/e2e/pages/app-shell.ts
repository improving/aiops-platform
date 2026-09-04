import { expect, type Locator, type Page } from "@playwright/test";

/**
 * The parts of the page every screen shares: header navigation, theme
 * dropdown, page heading, footer, and toasts.
 */
export class AppShell {
  readonly header: Locator;
  readonly brand: Locator;
  readonly heading: Locator;
  readonly footer: Locator;
  readonly toasts: Locator;
  readonly themeToggle: Locator;
  readonly mobileMenuButton: Locator;

  constructor(readonly page: Page) {
    this.header = page.locator("header");
    this.brand = this.header.getByRole("link", { name: "AI Hub" });
    this.heading = page.getByRole("heading", { level: 1 });
    this.footer = page.locator("footer");
    // Radix toast roots carry role="status".
    this.toasts = page.getByRole("status");
    this.themeToggle = this.header.getByRole("button", {
      name: "Toggle theme",
    });
    this.mobileMenuButton = this.header.getByRole("button", {
      name: "Open menu",
    });
  }

  async goto(path = "/") {
    await this.page.goto(path);
  }

  /** A top-level nav link (Notebooks, Develop). */
  navLink(label: string): Locator {
    return this.header.getByRole("link", { name: label, exact: true });
  }

  /** A top-level nav dropdown trigger (Models, Vector Databases). */
  navTrigger(label: string): Locator {
    return this.header.getByRole("button", { name: label, exact: true });
  }

  /** Open a dropdown and click the sub-item whose label starts with `item`. */
  async clickDropdownItem(menu: string, item: string) {
    await this.navTrigger(menu).click();
    const link = this.header.getByRole("link", {
      name: new RegExp(`^${item}\\b`),
    });
    await expect(link).toBeVisible();
    await link.click();
  }

  async expectHeading(text: string | RegExp) {
    await expect(this.heading).toHaveText(text);
  }

  /** The most recent toast whose text matches. */
  toast(text: string | RegExp): Locator {
    return this.toasts.filter({ hasText: text });
  }

  async chooseTheme(name: "Light" | "Dark" | "System") {
    await this.themeToggle.click();
    await this.page.getByRole("menuitem", { name, exact: true }).click();
  }

  /** The dialog currently open (confirmations, forms). */
  dialog(): Locator {
    return this.page.getByRole("dialog");
  }

  /** Confirm the shared DeleteButton dialog. */
  async confirmDelete() {
    const dialog = this.dialog().filter({ hasText: "Confirm Deletion" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Delete", exact: true }).click();
    await expect(dialog).toBeHidden();
  }
}
