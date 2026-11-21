import { test, expect } from "../fixtures";
import { AppShell } from "../pages/app-shell";
import { DevelopPage } from "../pages/develop";
import { KeycloakLoginPage, LoginPage } from "../pages/login";

const LANGFLOW_URL =
  process.env.E2E_LANGFLOW_URL ?? "https://langflow.127.0.0.1.nip.io";

test.describe("login and logout", { tag: "@cluster" }, () => {
  test.describe.configure({ mode: "serial" });

  // A fresh browser context: no saved Auth.js session, no Keycloak SSO
  // cookie, so the real login form is exercised.
  test.use({
    storageState: { cookies: [], origins: [] },
    // The Develop iframe loads Langflow behind the gateway, which sends a
    // browser without OIDC cookies to Keycloak; Keycloak's login page
    // refuses to render in a frame (frame-ancestors 'self'), and Chromium
    // reports that as a console error. Expected on a first visit; see
    // docs/local-dev.md "Iframe caveat". One combined pattern on purpose:
    // Playwright reads a `use` value of the form [x, object] as a fixture
    // tuple, so a list of two or more RegExps would lose all but the first
    // (see the `allowedConsoleErrors` note in e2e/fixtures.ts).
    allowedConsoleErrors: [
      /Failed to load resource|frame-ancestors|X-Frame-Options|Download the React DevTools|\[Fast Refresh\]|favicon\.ico/,
    ],
  });

  test("a visitor is sent to /login, alice signs in, sees her name, and signs out", async ({
    page,
  }) => {
    // Unauthenticated: every page redirects to /login with a callbackUrl.
    await page.goto("/");
    await expect(page).toHaveURL(/\/login\?callbackUrl=%2F$/);

    const login = new LoginPage(page);
    await login.signInButton.click();

    const keycloak = new KeycloakLoginPage(page);
    await keycloak.signIn("alice", "alice");
    await page.waitForURL((url) => url.pathname === "/");

    const shell = new AppShell(page);
    await expect(shell.heading).toBeVisible();
    const menu = await shell.openUserMenu();
    await expect(menu).toContainText("Alice Example");
    await expect(menu).toContainText("alice@example.test");
    await page.keyboard.press("Escape");
    await expect(menu).toBeHidden();

    // Signed in, the Develop page embeds Langflow from its gateway host.
    // Only the src is checked: the frame content is Keycloak's or
    // Langflow's, depending on the cookies this context holds.
    const develop = new DevelopPage(page);
    await develop.open();
    await develop.expectHeading("Interactively Develop AI Applications");
    await expect(develop.notConfigured).toHaveCount(0);
    await develop.expectEmbeddedFrom(LANGFLOW_URL);

    // Sign out ends the Keycloak session and lands on /login; the home
    // page needs a login again.
    await shell.goto("/");
    await shell.signOut();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto("/");
    await expect(page).toHaveURL(/\/login\?callbackUrl=%2F$/);
  });
});
