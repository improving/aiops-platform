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
  /** The avatar button; rendered only when the UI runs with AUTH_MODE=oidc. */
  readonly userMenuButton: Locator;

  constructor(readonly page: Page) {
    this.header = page.locator("header");
    this.brand = this.header.getByRole("link", { name: "AI Hub" });
    this.heading = page.getByRole("heading", { level: 1 });
    this.footer = page.locator("footer");
    // Radix renders each toast as an <li role="status"> plus a hidden
    // announcement <div role="status">; keep only the visible list item.
    this.toasts = page.locator('li[role="status"]');
    this.themeToggle = this.header.getByRole("button", {
      name: "Toggle theme",
    });
    this.mobileMenuButton = this.header.getByRole("button", {
      name: "Open menu",
    });
    this.userMenuButton = this.header.getByRole("button", {
      name: "User menu",
    });
  }

  /** Open the user menu; the returned locator holds the name, email and "Sign out". */
  async openUserMenu(): Promise<Locator> {
    await this.userMenuButton.click();
    const menu = this.page.getByRole("menu");
    await expect(menu).toBeVisible();
    return menu;
  }

  /** Sign out through the user menu; ends on /login after the Keycloak logout. */
  async signOut() {
    const menu = await this.openUserMenu();
    await menu.getByRole("menuitem", { name: "Sign out" }).click();
    await this.page.waitForURL((url) => url.pathname === "/login");
  }

  async goto(path = "/") {
    await this.page.goto(path);
    // Pages fetch their data on mount and re-render; wait for that to settle
    // so a click right after goto is not swallowed by the re-render, but
    // never fail a test on it: on a loaded machine the catalog pages keep
    // fetching images and are never idle.
    await this.page
      .waitForLoadState("networkidle", { timeout: 10_000 })
      .catch(() => {});
  }

  /**
   * Click a link and wait for the URL to match. A click that lands during a
   * re-render can be lost on slow CI runners, so retry it once before the
   * assertion timeout expires.
   */
  async navigateByClick(link: Locator, url: RegExp) {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      await link.click();
      try {
        await this.page.waitForURL(url, { timeout: 5_000 });
        return;
      } catch {
        // retry once
      }
    }
    await expect(this.page).toHaveURL(url);
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

  /**
   * Confirm the shared DeleteButton dialog. `timeout` bounds how long the
   * delete call may take (Helm uninstalls are slow).
   */
  async confirmDelete(timeout?: number) {
    const dialog = this.dialog().filter({ hasText: "Confirm Deletion" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Delete", exact: true }).click();
    await expect(dialog).toBeHidden({ timeout });
  }
}
