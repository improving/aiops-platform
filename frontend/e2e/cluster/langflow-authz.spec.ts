import { test, expect } from "../fixtures";

const LANGFLOW_URL =
  process.env.E2E_LANGFLOW_URL ?? "https://langflow.127.0.0.1.nip.io";

// Langflow is protected by gateway OIDC alone: any realm user gets in and
// the control plane never sees the request. Adding an ext-authz check was
// tried (#30) and reverted, because it needs forwardAccessToken, which puts
// the platform's token in Authorization and makes Langflow answer 401 to
// its own API. See the manifest and the #29 plan for the bridge that would
// let the check come back. These two tests pin what the gateway does give
// us today, and the first one also catches the regression that reverting
// fixed: a page that loads but whose API calls all fail.
test.describe("Langflow authorization", { tag: "@cluster" }, () => {
  test("a signed-in member is let through to Langflow", async ({ page }) => {
    // The default storageState is alice's, and her Keycloak SSO session
    // completes the gateway's OIDC flow without the login form.
    // networkidle, not domcontentloaded: Langflow bootstraps its own
    // session with an XHR after the document loads, and the API check
    // below needs that to have happened.
    const response = await page.goto(LANGFLOW_URL, {
      waitUntil: "networkidle",
    });

    expect(response?.status()).toBe(200);
    // Landed on Langflow itself, not bounced to Keycloak.
    expect(new URL(page.url()).host).toBe(new URL(LANGFLOW_URL).host);
    // Status and title are not enough: Langflow's own login page and its
    // "could not load flows" error state both answer 200 with the same
    // title. Ask its API, which needs a token it accepts.
    const flows = await page.request.get(
      `${LANGFLOW_URL}/api/v1/flows/?get_all=true`
    );
    expect(flows.status()).toBe(200);
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

  test("the Develop page's embedded Langflow actually loads", async ({
    page,
  }) => {
    // The iframe is cross-site (localhost:3000 embedding the gateway host),
    // so every cookie involved is third-party there. With the defaults the
    // gateway's OIDC flow ended at /oauth2/callback with "OAuth flow
    // failed", and once that was fixed Langflow's own session cookie was
    // still not sent and the frame sat on "Loading..." -- while the same
    // URL worked in a tab. Asserting the iframe's src, which is all the
    // older specs did, catches neither.
    await page.goto("/develop", { waitUntil: "networkidle" });

    const frame = page.frameLocator('iframe[title="Develop Environment"]');
    // Real Langflow chrome, not its login page and not an error card.
    await expect(
      frame.getByText(/create a flow|starter project|projects/i).first()
    ).toBeVisible({ timeout: 60_000 });
  });
});
