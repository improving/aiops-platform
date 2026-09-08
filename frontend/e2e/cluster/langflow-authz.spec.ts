import { authStatePath, test, expect } from "../fixtures";

const LANGFLOW_URL =
  process.env.E2E_LANGFLOW_URL ?? "https://langflow.127.0.0.1.nip.io";

// Langflow runs on platform identity: the gateway logs the browser in,
// asks the control plane whether this member may open Langflow, and
// forwards the access token, which Langflow verifies itself and turns
// into a Langflow user per platform user. These tests pin all three
// halves: who gets in, who is kept out, and that two members are two
// users. Status and title prove nothing here -- Langflow's login page
// and its error state both answer 200 with the same title -- so every
// assertion asks its API.
test.describe("Langflow on platform identity", { tag: "@cluster" }, () => {
  test("a request with no session never reaches Langflow", async ({
    browser,
  }) => {
    const context = await browser.newContext({
      storageState: { cookies: [], origins: [] },
      ignoreHTTPSErrors: true,
    });
    try {
      const page = await context.newPage();
      await page.goto(LANGFLOW_URL, { waitUntil: "domcontentloaded" });
      // Compare hosts, not substrings: Keycloak's URL carries the
      // Langflow host inside its own redirect_uri parameter.
      const landed = new URL(page.url());
      expect(landed.host).not.toBe(new URL(LANGFLOW_URL).host);
      expect(landed.pathname).toContain(
        "/realms/aiops/protocol/openid-connect"
      );
    } finally {
      await context.close();
    }
  });

  test("a service account is refused by the control plane, with the reason", async ({
    browser,
    api,
  }) => {
    // The bearer skips the OIDC redirect (passThroughAuthHeader) and
    // reaches ext-authz, which is where it must stop.
    const token = await api.accessToken();
    expect(token, "the cluster tier has an automation token").toBeTruthy();
    const context = await browser.newContext({
      storageState: { cookies: [], origins: [] },
      ignoreHTTPSErrors: true,
    });
    try {
      const response = await context.request.get(
        `${LANGFLOW_URL}/api/v1/users/whoami`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      expect(response.status()).toBe(403);
      expect((await response.json()).detail).toContain("service accounts");
    } finally {
      await context.close();
    }
  });
});

// Langflow's bundle logs three errors of its own on every load under
// external auth, all by design: its auto-login probe (GET /api/v1/auto_login)
// answers 403 with auto_login:false, its refresh attempt with no refresh
// cookie (POST /api/v1/refresh) answers 401, and it prints "Duplicate
// request" for a request it coalesced. None of them is ours to fix, and the
// page renders and answers as the right user regardless (measured). One
// combined pattern: the fixture explains why the override takes only one.
test.describe("Langflow's pages", { tag: "@cluster" }, () => {
  // Only the tests that load Langflow's bundle carry the allow-list
  // (the two-members test loads it to establish each gateway session).
  test.use({
    allowedConsoleErrors: [/Failed to load resource|Duplicate request/],
  });

  test("two members are two users, and one's variables are not the other's", async ({
    page,
    asUser,
  }) => {
    await page.goto(LANGFLOW_URL, { waitUntil: "networkidle" });
    const name = `e2e-isolation-${Date.now()}`;
    const created = await page.request.post(
      `${LANGFLOW_URL}/api/v1/variables/`,
      {
        data: {
          name,
          value: "alice-only",
          type: "Generic",
          default_fields: [],
        },
      }
    );
    expect(created.status(), await created.text()).toBe(201);
    const id = (await created.json()).id;

    try {
      // The fixture owns bob's context and closes it after the test.
      const bob = await asUser("bob");
      const bobPage = await bob.newPage();
      await bobPage.goto(LANGFLOW_URL, { waitUntil: "networkidle" });
      const who = await (
        await bobPage.request.get(`${LANGFLOW_URL}/api/v1/users/whoami`)
      ).json();
      expect(who.username).toBe("bob");
      const theirs = await (
        await bobPage.request.get(`${LANGFLOW_URL}/api/v1/variables/`)
      ).json();
      expect(theirs.map((v: { name: string }) => v.name)).not.toContain(name);
    } finally {
      await page.request.delete(`${LANGFLOW_URL}/api/v1/variables/${id}`);
    }
  });

  test("a signed-in member is Langflow's user of the same name", async ({
    page,
  }) => {
    // networkidle: Langflow bootstraps its session with an XHR after the
    // document loads (GET /api/v1/session), and the API checks below
    // need the gateway session that navigation established.
    const response = await page.goto(LANGFLOW_URL, {
      waitUntil: "networkidle",
    });
    expect(response?.status()).toBe(200);
    expect(new URL(page.url()).host).toBe(new URL(LANGFLOW_URL).host);

    const me = await page.request.get(`${LANGFLOW_URL}/api/v1/users/whoami`);
    expect(me.status()).toBe(200);
    const user = await me.json();
    expect(user.username).toBe("alice");
    expect(user.is_superuser).toBe(false);

    const flows = await page.request.get(
      `${LANGFLOW_URL}/api/v1/flows/?get_all=true`
    );
    expect(flows.status()).toBe(200);
  });

  test("a browser from before the switch, holding Langflow's old cookies, still gets in", async ({
    browser,
  }) => {
    // Before platform identity every browser held Langflow's own
    // access_token_lf and refresh_token_lf for the shared user. The
    // bundle sends the first as a bearer, which skips the gateway login
    // (passThroughAuthHeader) and is refused by Envoy's JWT check; the
    // bundle must then drop its cookies and come back through the
    // login rather than loop. Reproduced here instead of in a stale
    // real browser.
    const context = await browser.newContext({
      storageState: authStatePath("alice"),
      ignoreHTTPSErrors: true,
    });
    try {
      await context.addCookies(
        ["access_token_lf", "refresh_token_lf", "apikey_tkn_lflw"].map(
          (name) => ({
            name,
            value: "stale-from-the-auto-login-days",
            url: LANGFLOW_URL,
            secure: true,
            sameSite: "None" as const,
          })
        )
      );
      const page = await context.newPage();
      await page.goto(LANGFLOW_URL, { waitUntil: "networkidle" });
      await expect(
        page
          .getByText(
            /welcome to langflow|create a flow|starter project|projects/i
          )
          .first()
      ).toBeVisible({ timeout: 60_000 });
      const me = await page.request.get(`${LANGFLOW_URL}/api/v1/users/whoami`);
      expect(me.status()).toBe(200);
      expect((await me.json()).username).toBe("alice");
    } finally {
      await context.close();
    }
  });

  test("the Develop page provisions the organization into Langflow", async ({
    page,
  }) => {
    // Loading the page calls POST /v1alpha1/langflow/provision as alice,
    // which writes Langflow's "OpenAI Compatible" provider variables on
    // her Langflow account; the panel reports it, and Langflow's own
    // model list for that provider now comes from the organization's
    // LiteLLM key.
    await page.goto("/develop", { waitUntil: "networkidle" });
    const panel = page.getByRole("region", { name: /Langflow for/ });
    await expect(panel).toContainText("Signed in to Langflow as alice");
    await expect(panel).toContainText("OpenAI Compatible");
    await expect(panel.getByRole("alert")).toHaveCount(0);

    const variables = await (
      await page.request.get(`${LANGFLOW_URL}/api/v1/variables/`)
    ).json();
    const names = variables.map((v: { name: string }) => v.name);
    expect(names).toContain("OPENAI_COMPATIBLE_BASE_URL");
    expect(names).toContain("OPENAI_COMPATIBLE_API_KEY");

    // What the Language Model picker offers under that provider: the
    // organization's models by their LiteLLM names, live.
    const catalogue = await (
      await page.request.get(
        `${LANGFLOW_URL}/api/v1/models?provider=OpenAI%20Compatible`
      )
    ).json();
    const offered = catalogue.flatMap(
      (p: { models?: { model_name: string }[] }) =>
        (p.models ?? []).map((m) => m.model_name)
    );
    expect(offered.some((n: string) => /^(inst|prov)-/.test(n))).toBe(true);
  });

  test("the Develop page's embedded Langflow actually loads", async ({
    page,
  }) => {
    // Cross-site iframe: every cookie involved is third-party there. With
    // the defaults the gateway's OIDC flow ended at /oauth2/callback with
    // "OAuth flow failed". Asserting the iframe's src catches nothing.
    await page.goto("/develop", { waitUntil: "networkidle" });
    const frame = page.frameLocator('iframe[title="Develop Environment"]');
    // A member's fresh account lands on the "Welcome to Langflow" empty
    // state; an account with flows lands on its projects.
    await expect(
      frame
        .getByText(
          /welcome to langflow|create a flow|starter project|projects/i
        )
        .first()
    ).toBeVisible({ timeout: 60_000 });
  });
});
