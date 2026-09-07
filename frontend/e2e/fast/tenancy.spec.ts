import {
  test,
  expect,
  FAILED_RESOURCE,
  ORG_COOKIE,
  shortId,
} from "../fixtures";
import { AppShell } from "../pages/app-shell";
import { OrganizationPage } from "../pages/organization";

// AUTH_MODE=disabled with TEST_MODE=true on the managed backend: X-Dev-User
// (set from the aiops_dev_user cookie by src/proxy.ts) picks one of five
// identities, and organization "other" is seeded with dev (admin) and
// outsider (member) in it (backend/auth/dev_users.py).

test.describe("organization switcher", () => {
  test("the user menu shows the active organization and lists both memberships for dev", async ({
    page,
    api,
  }) => {
    const shell = new AppShell(page);
    await shell.goto("/");
    const current = await api.currentOrganization();
    expect(current.slug).toBe("default");
    // The label lives in the menu content, which Radix renders only while
    // the menu is open; the switcher helper opens both levels.
    const submenu = await shell.openOrganizationSwitcher();
    await expect(shell.organizationLabel()).toContainText(current.name);

    const mine = await api.organizations();
    // Another worker may have created an organization in the meantime.
    expect(mine.organizations.map((o) => o.slug)).toEqual(
      expect.arrayContaining(["default", "other"])
    );
    for (const membership of mine.organizations) {
      await expect(
        submenu.getByRole("menuitemradio", {
          name: `${membership.name} · ${membership.role}`,
        })
      ).toBeVisible();
    }
  });

  test("switching sets the aiops_org cookie and reloads into the other organization", async ({
    page,
    context,
  }) => {
    const shell = new AppShell(page);
    await shell.goto("/");
    await shell.switchOrganization("Other");
    await expect(shell.organizationLabel()).toContainText("Other");
    const cookie = (await context.cookies()).find((c) => c.name === ORG_COOKIE);
    expect(cookie?.value).toBe("other");
    expect(cookie?.sameSite).toBe("Lax");
    const current = await page.request.get(
      "/api/v1alpha1/organizations/current"
    );
    expect((await current.json()).slug).toBe("other");
  });

  test("outsider sees an empty instance list", async ({ asUser, userApi }) => {
    const ctx = await asUser("outsider");
    const page = await ctx.newPage();
    const shell = new AppShell(page);
    await shell.goto("/models/endpoints");
    await shell.waitForLoaded();
    await expect(page.getByText("No model instances yet.")).toBeVisible();
    const outsider = await userApi("outsider");
    expect(await outsider.inferenceInstances()).toEqual([]);
    expect((await outsider.currentOrganization()).slug).toBe("other");
  });
});

test.describe("stale organization cookie", () => {
  test.use({ allowedConsoleErrors: [FAILED_RESOURCE] });

  test("a cookie for an organization the user is not in is cleared after one reload", async ({
    page,
    context,
    baseURL,
  }) => {
    await context.addCookies([
      { name: ORG_COOKIE, value: "nowhere", url: baseURL! },
    ]);
    const shell = new AppShell(page);
    await shell.goto("/usage");
    // The 403 from the backend clears the cookie and reloads once.
    await expect
      .poll(async () =>
        (await context.cookies()).some((c) => c.name === ORG_COOKIE)
      )
      .toBe(false);
    await shell.openUserMenu();
    await expect(shell.organizationLabel()).toContainText("Default");
  });
});

test.describe("organization page", () => {
  test("lists members, invites and withdraws", async ({ page, api }) => {
    const org = new OrganizationPage(page);
    await org.open();
    await org.expectHeading("Organization");
    await org.waitForLoaded();
    await expect(org.memberRow("dev@example.test")).toBeVisible();
    await expect(org.memberRow("dev@example.test")).toContainText("admin");

    const email = `carol-${shortId()}@example.test`;
    await org.invite(email, "member");
    await expect(org.invitationRow(email)).toContainText("Pending");
    await expect(
      org.invitationRow(email).getByRole("button", { name: "Copy sign-in URL" })
    ).toBeVisible();
    await org.withdraw(email);
    await expect(org.invitationRow(email)).toHaveCount(0);
    expect((await api.currentOrganization()).member_count).toBeGreaterThan(0);
  });

  test("a platform admin creates an organization and lands in it", async ({
    page,
    api,
  }) => {
    const org = new OrganizationPage(page);
    await org.open();
    const slug = `acme-${shortId()}`;
    await org.createOrganization(slug, `Acme ${slug}`);
    await expect(org.organizationLabel()).toContainText(`Acme ${slug}`);
    const mine = await api.organizations();
    expect(mine.organizations.some((o) => o.slug === slug)).toBe(true);
  });

  test("a member sees the summary only", async ({ asUser }) => {
    const ctx = await asUser("alice");
    const page = await ctx.newPage();
    const org = new OrganizationPage(page);
    await org.open();
    await org.waitForLoaded();
    await expect(
      page.getByText("Only organization admins can manage members.")
    ).toBeVisible();
    await expect(org.inviteButton).toHaveCount(0);
    await expect(org.createOrganizationButton).toHaveCount(0);
  });
});
