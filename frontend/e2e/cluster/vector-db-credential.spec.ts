import {
  test,
  expect,
  helmReleases,
  waitForHelmReleaseGone,
} from "../fixtures";
import { VectorDBCatalogPage } from "../pages/vector-db-catalog";
import { VectorDBEndpointsPage } from "../pages/vector-db-endpoints";

const CREATE_TIMEOUT = 3 * 60_000;
const READY_TIMEOUT = 5 * 60_000;
const DELETE_TIMEOUT = 3 * 60_000;
// The API-key SecurityPolicy is programmed into Envoy a moment after the
// route; until then the -api host is open.
const POLICY_TIMEOUT = 90_000;

test.describe("vector database credential", { tag: "@cluster" }, () => {
  test.describe.configure({ mode: "serial" });

  const leftovers: string[] = [];

  // Delete as admin: the automation user behind `api` is a member and may
  // not delete what alice created.
  test.afterEach(async ({ api, userApi }) => {
    for (const id of leftovers.splice(0)) {
      await (await userApi("admin")).deleteVectorDBInstance(id);
      await expect
        .poll(async () => (await api.vectorDBInstances()).map((i) => i.id), {
          timeout: DELETE_TIMEOUT,
        })
        .not.toContain(id);
      await waitForHelmReleaseGone(id.slice(0, 8), DELETE_TIMEOUT);
    }
  });

  test("alice deploys Qdrant, reveals its key once, and the -api host enforces it", async ({
    page,
    api,
    request,
  }) => {
    const before = new Set((await api.vectorDBInstances()).map((i) => i.id));

    const catalog = new VectorDBCatalogPage(page);
    await catalog.open();
    await catalog.launch("Qdrant");
    const createDialog = catalog.createDialog();
    await expect(createDialog).toBeVisible();
    const serviceType = catalog.serviceTypeSelect();
    if ((await serviceType.count()) > 0) {
      await serviceType.click();
      await page.getByRole("option", { name: "ClusterIP" }).click();
    }
    await createDialog.getByRole("button", { name: "Create" }).click();
    await expect(
      catalog.toast("Vector database instance created successfully")
    ).toBeVisible({ timeout: CREATE_TIMEOUT });
    await expect(page).toHaveURL(/\/vector-databases\/endpoints$/);

    const created = (await api.vectorDBInstances()).filter(
      (i) => !before.has(i.id)
    );
    expect(created, "exactly one new instance").toHaveLength(1);
    const id = created[0].id;
    leftovers.push(id);
    const release = `qdrant-${id.slice(0, 8)}`;
    expect(helmReleases()).toContain(release);

    const ready = await api.waitForVectorDBReady(id, READY_TIMEOUT);
    const instance = await api.vectorDBInstance(id);
    const apiEndpoint = (instance as { api_endpoint?: string | null } | null)
      ?.api_endpoint;
    expect(apiEndpoint, "the SDK endpoint behind the gateway").toMatch(
      /^https:\/\/vdb-[0-9a-f]{8}-api\./
    );
    const collectionsUrl = `${apiEndpoint!.replace(/\/$/, "")}/collections`;

    // Reveal the key from the endpoints page.
    const endpoints = new VectorDBEndpointsPage(page);
    await endpoints.open();
    const card = endpoints.cardById(id);
    await expect(card).toBeVisible();
    await expect(card).toContainText("Ready");
    await expect(card).toContainText(ready.endpoint!);
    await expect(card).toContainText(apiEndpoint!);

    let dialog = await endpoints.revealCredential(card);
    await expect(dialog).toContainText("This key is shown once");
    const key = (await endpoints.credentialValue(dialog).textContent())?.trim();
    expect(key, "the dialog shows the key").toMatch(/^\S{16,}$/);
    await expect(dialog.getByLabel("API endpoint", { exact: true })).toHaveText(
      apiEndpoint!
    );
    await endpoints.closeCredentialDialog(dialog);

    // The gateway rejects a request without the key and admits one with it.
    await expect
      .poll(async () => (await request.get(collectionsUrl)).status(), {
        message: `${collectionsUrl} without a key`,
        timeout: POLICY_TIMEOUT,
        intervals: [5_000],
      })
      .toBe(401);
    await expect
      .poll(
        async () =>
          (
            await request.get(collectionsUrl, {
              headers: { "api-key": key! },
            })
          ).status(),
        {
          message: `${collectionsUrl} with the api-key header`,
          timeout: POLICY_TIMEOUT,
          intervals: [5_000],
        }
      )
      .toBe(200);
    const withKey = await request.get(collectionsUrl, {
      headers: { "api-key": key! },
    });
    expect(await withKey.json()).toMatchObject({ status: "ok" });

    // The backend hands the value out once.
    dialog = await endpoints.revealCredential(card);
    await expect(dialog).toContainText("This key was already revealed.");
    await expect(endpoints.credentialValue(dialog)).toHaveCount(0);
    await endpoints.closeCredentialDialog(dialog);

    // Delete through the UI as the owner.
    await endpoints.deleteButton(card).click();
    await endpoints.confirmDelete(DELETE_TIMEOUT);
    await expect(endpoints.toast("Item deleted successfully")).toBeVisible();
    await expect(card).toHaveCount(0);
    await expect
      .poll(async () => (await api.vectorDBInstances()).map((i) => i.id), {
        timeout: DELETE_TIMEOUT,
      })
      .not.toContain(id);
    await waitForHelmReleaseGone(release, DELETE_TIMEOUT);
    leftovers.length = 0;
  });
});
