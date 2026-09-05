// Logs alice, bob and admin into Keycloak once and saves each session as
// Playwright storage state, so the `cluster` project's tests (and the
// `asUser` fixture) can start already signed in instead of clicking through
// the login form in every test.
//
// Runs as the `setup` project (see playwright.config.ts); the `cluster`
// project depends on it. Not from `../fixtures`: the console guard would
// fail on Keycloak's own page noise, and the `api` fixture would fetch an
// automation token this file never uses.
import { test as setup, expect } from "@playwright/test";
import * as fs from "node:fs";
import * as path from "node:path";
import { authStatePath, type E2EUser } from "./fixtures";

const USERS: { name: E2EUser; password: string }[] = [
  { name: "alice", password: "alice" },
  { name: "bob", password: "bob" },
  { name: "admin", password: "admin" },
];

for (const { name, password } of USERS) {
  setup(`log in as ${name}`, async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("button", { name: "Sign in with Keycloak" }).click();

    // Keycloak's own login form, not the app's; selectors per
    // docs/superpowers/plans/2026-09-04-authentication-identity-notes.md
    // section 5 (confirmed against Keycloak 26.7.3's login.ftl).
    await page.locator("#username").fill(name);
    await page.locator("#password").fill(password);
    await page.locator("#kc-login").click();

    await page.waitForURL((url) => url.pathname === "/");
    // The session cookie is set by the time the home page renders its
    // heading; storageState right after waitForURL can race the redirect.
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    const statePath = authStatePath(name);
    fs.mkdirSync(path.dirname(statePath), { recursive: true });
    await page.context().storageState({ path: statePath });
  });
}
