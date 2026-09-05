import type { Page } from "@playwright/test";
import {
  test,
  expect,
  helmReleases,
  shortId,
  waitForHelmReleaseGone,
} from "../fixtures";
import { KeycloakLoginPage } from "../pages/login";
import { NotebookFormPage } from "../pages/notebook-form";
import { NotebookDetailsPage, NotebookListPage } from "../pages/notebooks";

const CREATE_TIMEOUT = 2 * 60_000;
const RUNNING_TIMEOUT = 6 * 60_000;
const DELETE_TIMEOUT = 3 * 60_000;
// One gateway hop: OIDC redirect to Keycloak and back, ext-authz, then
// JupyterLab's first load.
const GATEWAY_TIMEOUT = 60_000;
// A "Running" pod does not mean the Jupyter server is listening yet; Envoy
// answers 503 ("upstream connect error") until it is.
const UPSTREAM_TIMEOUT = 3 * 60_000;
const UPSTREAM_ERRORS = [502, 503, 504];
const NOT_OWNER = "You do not own this notebook";

/**
 * Open `url` in `page` as `user`. The saved storage states hold a Keycloak
 * SSO cookie, so the gateway's OIDC redirect normally comes straight back;
 * a context that lost it is shown the form and signs in. A 502/503/504 from
 * the gateway is retried while the workload starts. Returns the final
 * navigation response.
 */
async function openThroughGateway(
  page: Page,
  url: string,
  user: { name: string; password: string }
) {
  const keycloak = new KeycloakLoginPage(page);
  const deadline = Date.now() + UPSTREAM_TIMEOUT;
  for (;;) {
    let response = await page.goto(url, { timeout: GATEWAY_TIMEOUT });
    if (await keycloak.signInIfShown(user.name, user.password)) {
      await page.waitForLoadState("load", { timeout: GATEWAY_TIMEOUT });
      // Cookies are set now; a second navigation gives the workload's (or
      // ext-authz's) own response rather than the last redirect hop.
      response = await page.goto(url, { timeout: GATEWAY_TIMEOUT });
    }
    expect(response, `navigation to ${url}`).toBeTruthy();
    if (
      !UPSTREAM_ERRORS.includes(response!.status()) ||
      Date.now() > deadline
    ) {
      return response!;
    }
    await page.waitForTimeout(5_000);
  }
}

test.describe(
  "notebook access through the gateway",
  { tag: "@cluster" },
  () => {
    test.describe.configure({ mode: "serial" });
    // Create (2 min) + Running (6 min) + the gateway checks + delete (3 min)
    // exceed the project's 10 minute default in the worst case.
    test.setTimeout(15 * 60_000);

    const leftovers: string[] = [];

    // Notebooks are visible to their owner and org admins only, so the
    // automation user behind `api` neither sees nor may delete alice's;
    // clean up as admin and confirm nothing of this spec is left in Helm.
    test.afterEach(async ({ userApi }) => {
      const admin = await userApi("admin");
      for (const id of leftovers.splice(0)) {
        await admin.deleteNotebook(id);
        await expect
          .poll(async () => (await admin.notebooks()).map((n) => n.id), {
            timeout: DELETE_TIMEOUT,
          })
          .not.toContain(id);
        await waitForHelmReleaseGone(id.slice(0, 8), DELETE_TIMEOUT);
      }
      expect(
        helmReleases().filter((n) => n.startsWith("e2e-nb-")),
        "no Helm release left for this spec"
      ).toEqual([]);
    });

    test("alice opens her notebook through the gateway; bob is refused and does not see it", async ({
      page,
      asUser,
      userApi,
    }) => {
      const name = `e2e-nb-${shortId()}`;
      const alice = await userApi("alice");

      const form = new NotebookFormPage(page);
      await form.open();
      await form.name.fill(name);
      await expect(form.cpu).toHaveValue("0.5");
      await expect(form.memory).toHaveValue("1");
      await expect(form.storage).toHaveValue("5");
      await expect(form.gpuSwitch).not.toBeChecked();
      await form.launchButton.click();
      await expect(form.toast("Notebook created")).toBeVisible({
        timeout: CREATE_TIMEOUT,
      });
      await expect(page).toHaveURL(/\/notebooks$/);

      const record = (await alice.notebooks()).find((n) => n.name === name);
      expect(record, `notebook ${name} exists in the API`).toBeTruthy();
      const id = record!.id;
      leftovers.push(id);

      const running = await alice.waitForNotebookStatus(
        id,
        "Running",
        RUNNING_TIMEOUT
      );
      const endpoint = running.endpoint!;
      expect(endpoint, "the stored endpoint is a gateway URL").toMatch(
        /^https:\/\/nb-[0-9a-f]{8}\./
      );
      expect(endpoint).toContain(id.replace(/-/g, "").slice(-8));

      // The owner reaches JupyterLab. A separate alice context: JupyterLab
      // logs console errors of its own that the default page's guard would
      // count against the app.
      const alicePage = await (await asUser("alice")).newPage();
      const aliceResponse = await openThroughGateway(alicePage, endpoint, {
        name: "alice",
        password: "alice",
      });
      expect(aliceResponse.status(), "alice through the gateway").toBe(200);
      await expect
        .poll(
          async () =>
            /JupyterLab/.test(await alicePage.title()) ||
            /jp-|jupyter/i.test(await alicePage.content()),
          {
            message: "JupyterLab did not render for alice",
            timeout: GATEWAY_TIMEOUT,
          }
        )
        .toBe(true);
      await alicePage.close();

      // Another member of the organization is refused by ext-authz.
      const bobContext = await asUser("bob");
      const bobPage = await bobContext.newPage();
      const bobResponse = await openThroughGateway(bobPage, endpoint, {
        name: "bob",
        password: "bob",
      });
      const bobBody = await bobPage.content();
      expect(
        bobResponse.status() === 403 || bobBody.includes(NOT_OWNER),
        `bob through the gateway: status ${bobResponse.status()}`
      ).toBe(true);

      // Bob's list does not show it. The list renders nothing until its
      // first fetch answers; wait for it so an empty page is not mistaken
      // for "not listed".
      const bobList = new NotebookListPage(bobPage);
      const listed = bobPage.waitForResponse(
        (res) =>
          res.request().method() === "GET" &&
          /\/api\/v1alpha1\/notebooks\/?$/.test(new URL(res.url()).pathname)
      );
      await bobList.open();
      expect((await listed).status(), "GET /notebooks as bob").toBe(200);
      await expect(bobList.heading).toBeVisible();
      await expect(bobList.notebookLink(name)).toHaveCount(0);
      await bobPage.close();

      // Nor does the API hand it to him.
      const bob = await userApi("bob");
      expect((await bob.notebooks()).map((n) => n.id)).not.toContain(id);
      const bobGet = await bob.get(`/notebooks/${id}`);
      expect(bobGet.status(), "GET /notebooks/<id> as bob").toBe(403);
      expect(await bobGet.json()).toMatchObject({ detail: NOT_OWNER });

      // Alice deletes it from the details page.
      const details = new NotebookDetailsPage(page);
      await details.open(id);
      await details.expectHeading("Notebook Details");
      await details.deleteButton.click();
      await details.confirmDelete(DELETE_TIMEOUT);
      await expect(details.toast("Item deleted successfully")).toBeVisible();
      await expect(page).toHaveURL(/\/notebooks$/);

      await expect
        .poll(async () => (await alice.notebooks()).map((n) => n.id), {
          timeout: DELETE_TIMEOUT,
        })
        .not.toContain(id);
      await waitForHelmReleaseGone(id.slice(0, 8), DELETE_TIMEOUT);
      leftovers.length = 0;
    });
  }
);
