import type { Browser, BrowserContext } from "@playwright/test";
import {
  test,
  expect,
  helmReleases,
  waitForHelmReleaseGone,
  authStatePath,
  ORG_COOKIE,
  BackendApi,
  type E2EUser,
} from "../fixtures";
import { AppShell } from "../pages/app-shell";
import { AuditPage } from "../pages/audit";

const MODEL_TAG = "qwen3:0.6b";
const ACME = "e2e-acme";
const DELETE_TIMEOUT = 3 * 60_000;
// backend/auth/policy.py not_owner("inference instance").
const NOT_OWNER = "You do not own this inference instance";

async function ollamaLaunchBody(api: BackendApi) {
  const model = (await api.models()).find((m) => m.modelId === MODEL_TAG);
  const engine = (await api.engines()).find((e) => e.name === "Ollama");
  expect(
    model && engine,
    `${MODEL_TAG} and Ollama in the catalog`
  ).toBeTruthy();
  return { model: { id: model!.id }, engine: { id: engine!.id }, config: {} };
}

/**
 * A `BackendApi` for `user`, through the UI proxy, pinned to `org`.
 *
 * `src/proxy.ts` deletes any client-sent `X-Org` header and forwards the
 * organization only from the `aiops_org` cookie
 * (`headers.delete(ORG_HEADER)` before reading the cookie) -- so a
 * `userApi(name).withHeaders({ "X-Org": org })` call is silently ignored
 * and always resolves to the caller's own active organization. A fresh
 * `BrowserContext` with the cookie set is the only way to pin the
 * organization for a proxied call; it is independent of (and never
 * mutates) the `asUser`/`userApi` fixtures' cached contexts, so admin's
 * and bob's default-organization sessions used elsewhere in this test are
 * unaffected. The caller collects the returned context and closes it in
 * `test.afterEach` (see `contexts` below).
 */
async function orgScopedApi(
  browser: Browser,
  baseURL: string,
  user: E2EUser,
  org: string
) {
  const ctx = await browser.newContext({
    baseURL,
    storageState: authStatePath(user),
    ignoreHTTPSErrors: true,
  });
  await ctx.addCookies([{ name: ORG_COOKIE, value: org, url: baseURL }]);
  const proxyURL = `${baseURL.replace(/\/$/, "")}/api`;
  return { api: new BackendApi(ctx.request, proxyURL, "disabled"), ctx };
}

test.describe("tenancy isolation", { tag: "@cluster" }, () => {
  test.setTimeout(15 * 60_000);
  const leftovers: string[] = [];
  // BrowserContexts opened by orgScopedApi, closed below regardless of
  // where in the test a failure happens.
  const contexts: BrowserContext[] = [];

  test.afterEach(async ({ userApi }) => {
    // Close first: cheap, and waitForHelmReleaseGone below can take
    // minutes or throw, which must not leak these contexts.
    for (const ctx of contexts.splice(0)) {
      await ctx.close();
    }
    const admin = await userApi("admin");
    for (const id of leftovers.splice(0)) {
      await admin.deleteInferenceInstance(id);
      await waitForHelmReleaseGone(id.slice(0, 8), DELETE_TIMEOUT);
    }
  });

  test("alice and bob in different organizations cannot see each other's instance; a token lists instances", async ({
    api,
    asUser,
    userApi,
    baseURL,
    browser,
  }) => {
    // 1. The platform admin creates e2e-acme (kept between runs) and
    //    invites bob into it; both calls tolerate "already there". Creating
    //    an organization is a platform-admin action with no organization
    //    scope, so the plain (proxied) admin session is enough; the
    //    invitation is scoped to e2e-acme and needs the cookie-pinned
    //    session (see orgScopedApi).
    const admin = await userApi("admin");
    const created = await admin.post("/organizations", {
      slug: ACME,
      name: "E2E Acme",
    });
    expect([201, 409]).toContain(created.status());
    const acmeAdmin = await orgScopedApi(browser, baseURL!, "admin", ACME);
    contexts.push(acmeAdmin.ctx);
    const invited = await acmeAdmin.api.post(
      "/organizations/current/invitations",
      { email: "bob@example.test", role: "member" }
    );
    expect([201, 409]).toContain(invited.status());

    // 2. Bob's next request accepts the invitation; the cookie-pinned
    //    session resolves him into e2e-acme.
    const bob = await userApi("bob");
    const bobOrgs = (await bob.organizations()).organizations.map(
      (o) => o.slug
    );
    expect(bobOrgs).toContain(ACME);
    const bobInAcme = await orgScopedApi(browser, baseURL!, "bob", ACME);
    contexts.push(bobInAcme.ctx);
    expect((await bobInAcme.api.currentOrganization()).slug).toBe(ACME);
    const bobInNoSuchOrg = await orgScopedApi(
      browser,
      baseURL!,
      "bob",
      "no-such-org"
    );
    contexts.push(bobInNoSuchOrg.ctx);
    const denied = await bobInNoSuchOrg.api.get("/organizations/current");
    expect(denied.status()).toBe(403);
    expect((await denied.json()).detail).toBe(
      "You are not a member of this organization"
    );

    // 3. Alice launches Ollama in the default organization.
    const alice = await userApi("alice");
    const instance = await alice.createInferenceInstance(
      await ollamaLaunchBody(alice)
    );
    leftovers.push(instance.id);
    expect(helmReleases()).toContain(`ollama-${instance.id.slice(0, 8)}`);

    // 4. Bob in e2e-acme cannot list or read it; bob in default still can.
    expect(
      (await bobInAcme.api.inferenceInstances()).some(
        (i) => i.id === instance.id
      )
    ).toBe(false);
    const forbidden = await bobInAcme.api.get(
      `/inferenceInstance/${instance.id}`
    );
    expect(forbidden.status()).toBe(403);
    expect((await forbidden.json()).detail).toBe(NOT_OWNER);
    expect(
      (await bob.inferenceInstances()).some((i) => i.id === instance.id)
    ).toBe(true);

    // 5. The same through the browser: the cookie set by the switcher.
    const bobContext = await asUser("bob");
    await bobContext.addCookies([
      { name: ORG_COOKIE, value: ACME, url: baseURL! },
    ]);
    const bobPage = await bobContext.newPage();
    const shell = new AppShell(bobPage);
    await shell.goto("/models/endpoints");
    await shell.waitForLoaded();
    await expect(bobPage.getByText("No model instances yet.")).toBeVisible();
    await shell.openUserMenu();
    await expect(shell.organizationLabel()).toContainText("E2E Acme");

    // 6. A personal token (a curl equivalent: Playwright's request against
    //    the backend with only the bearer) lists alice's instances. This
    //    goes straight at the backend (the `api` fixture, not the UI
    //    proxy), so a raw `Authorization` header works as sent.
    const minted = await alice.post("/tokens", {
      name: "e2e-read",
      scope: "read",
      expires_in_days: 1,
    });
    expect(minted.status(), await minted.text()).toBe(201);
    const { token, id: tokenId } = (await minted.json()) as {
      token: string;
      id: string;
    };
    expect(token).toMatch(/^aiops_[A-Za-z0-9]{8}_[A-Za-z0-9]{32}$/);
    const viaToken = api.withHeaders({ Authorization: `Bearer ${token}` });
    expect(
      (await viaToken.inferenceInstances()).some((i) => i.id === instance.id)
    ).toBe(true);
    // A read token is a viewer: it cannot launch.
    const refused = await viaToken.post(
      "/inferenceInstance",
      await ollamaLaunchBody(alice)
    );
    if (refused.status() === 201) {
      // Guard against a leaked release if the viewer check regresses.
      leftovers.push((await refused.json()).id);
    }
    expect(refused.status()).toBe(403);
    // Revoked: 401 with the fixed message.
    expect((await alice.remove(`/tokens/${tokenId}`)).status()).toBe(204);
    const revoked = await viaToken.get("/inferenceInstance");
    expect(revoked.status()).toBe(401);
    expect((await revoked.json()).detail).toBe("The token was revoked");

    // 7. The audit page shows the launch (spec section 8). Admin's cached
    //    session was never cookie-pinned to e2e-acme, so it is still in
    //    the default organization here, where alice's launch happened.
    const adminPage = await (await asUser("admin")).newPage();
    const audit = new AuditPage(adminPage);
    await audit.open();
    await audit.waitForLoaded();
    // A POST /inferenceInstance has no UUID in its path, so the row has
    // no resource id; match on kind, action and actor.
    const launch = audit
      .rows()
      .filter({ hasText: "inferenceInstance" })
      .filter({ hasText: "create" })
      .filter({ hasText: "alice@example.test" });
    // The event commits after the launch response; reload until listed.
    await expect
      .poll(
        async () => {
          await audit.open();
          await audit.waitForLoaded();
          return launch.count();
        },
        { timeout: 30_000 }
      )
      .toBeGreaterThan(0);
  });
});
