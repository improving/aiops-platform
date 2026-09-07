import { test, expect } from "../fixtures";

const LANGFLOW_URL =
  process.env.E2E_LANGFLOW_URL ?? "https://langflow.127.0.0.1.nip.io";

// The gateway's SecurityPolicy for the Langflow host carries extAuth
// (#30), so every request reaches the control plane's
// GET /v1alpha1/authz/route before Langflow sees it. The OIDC block alone
// only proved the realm had authenticated somebody.
test.describe("Langflow authorization", { tag: "@cluster" }, () => {
  test("a signed-in member is let through to Langflow", async ({ page }) => {
    // The default storageState is alice's, and her Keycloak SSO session
    // completes the gateway's OIDC flow without the login form.
    const response = await page.goto(LANGFLOW_URL, {
      waitUntil: "domcontentloaded",
    });

    expect(response?.status()).toBe(200);
    // Landed on Langflow itself, not bounced to Keycloak.
    expect(new URL(page.url()).host).toBe(new URL(LANGFLOW_URL).host);
    await expect(page).toHaveTitle(/langflow/i);
  });

  test("a request with no session never reaches Langflow", async ({
    browser,
  }) => {
    // A clean context: no Auth.js session and no Keycloak SSO cookie.
    const context = await browser.newContext({
      storageState: { cookies: [], origins: [] },
      ignoreHTTPSErrors: true,
    });
    try {
      const page = await context.newPage();
      await page.goto(LANGFLOW_URL, { waitUntil: "domcontentloaded" });

      // The gateway sends it to Keycloak instead. Compare hosts, not
      // substrings: Keycloak's URL carries the Langflow host inside its
      // own redirect_uri parameter.
      const landed = new URL(page.url());
      expect(landed.host).not.toBe(new URL(LANGFLOW_URL).host);
      expect(landed.pathname).toContain(
        "/realms/aiops/protocol/openid-connect"
      );
    } finally {
      await context.close();
    }
  });
});
