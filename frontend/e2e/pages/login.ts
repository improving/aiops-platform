import { expect, type Locator, type Page } from "@playwright/test";

/** The app's own /login page (src/app/login/page.tsx). */
export class LoginPage {
  readonly signInButton: Locator;

  constructor(readonly page: Page) {
    this.signInButton = page.getByRole("button", {
      name: "Sign in with Keycloak",
    });
  }

  async open() {
    await this.page.goto("/login");
  }
}

/**
 * Keycloak's login form (login.ftl, Keycloak 26.7), which the app and the
 * gateway both redirect to. The ids are Keycloak's, not ours; see
 * e2e/auth.setup.ts.
 */
export class KeycloakLoginPage {
  readonly username: Locator;
  readonly password: Locator;
  readonly submit: Locator;

  constructor(readonly page: Page) {
    this.username = page.locator("#username");
    this.password = page.locator("#password");
    this.submit = page.locator("#kc-login");
  }

  /** Whether the form is on screen right now (no waiting). */
  async isShown(): Promise<boolean> {
    return this.username.isVisible();
  }

  async signIn(user: string, password: string) {
    await expect(this.username).toBeVisible();
    await this.username.fill(user);
    await this.password.fill(password);
    await this.submit.click();
  }

  /**
   * Complete the form only when Keycloak shows it. A context that already
   * holds a Keycloak SSO cookie (the saved storage states do) is sent
   * straight back without a form.
   */
  async signInIfShown(user: string, password: string): Promise<boolean> {
    if (!(await this.isShown())) return false;
    await this.signIn(user, password);
    return true;
  }
}
