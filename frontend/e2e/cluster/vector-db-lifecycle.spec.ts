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
const DELETE_TIMEOUT = 2 * 60_000;

test.describe("vector database lifecycle", { tag: "@cluster" }, () => {
  test.describe.configure({ mode: "serial" });

  // Instances created by a test that has not cleaned up after itself.
  const leftovers: string[] = [];

  test.afterEach(async ({ api }) => {
    for (const id of leftovers.splice(0)) {
      await api.deleteVectorDBInstance(id);
      await waitForHelmReleaseGone(id.slice(0, 8));
    }
  });

  test("launch Qdrant, wait until it is Ready, then delete it", async ({
    page,
    api,
  }) => {
    const before = new Set((await api.vectorDBInstances()).map((i) => i.id));

    const catalog = new VectorDBCatalogPage(page);
    await catalog.open();
    await catalog.launch("Qdrant");
    const dialog = catalog.createDialog();
    await expect(dialog).toBeVisible();

    // Pick ClusterIP when the dialog offers a service type. Without a
    // LoadBalancer provider the backend falls back to the ClusterIP anyway.
    const serviceType = catalog.serviceTypeSelect();
    if ((await serviceType.count()) > 0) {
      await serviceType.click();
      await page.getByRole("option", { name: "ClusterIP" }).click();
    }

    await dialog.getByRole("button", { name: "Create" }).click();
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
    expect(created[0].vectorDB.name).toBe("Qdrant");
    const release = `qdrant-${id.slice(0, 8)}`;
    expect(helmReleases()).toContain(release);

    // The endpoints page lists the new instance.
    const endpoints = new VectorDBEndpointsPage(page);
    const card = endpoints.cardById(id);
    await expect(card).toBeVisible();
    await expect(card).toContainText("Qdrant");

    // Wait for readiness through the API, then confirm the UI agrees.
    const ready = await api.waitForVectorDBReady(id, READY_TIMEOUT);
    expect(ready.endpoint).toMatch(/^https?:\/\//);
    await page.reload();
    await expect(card).toContainText("Ready");
    await expect(card).toContainText(ready.endpoint!);
    await expect(
      card.getByRole("link", { name: ready.endpoint! })
    ).toHaveAttribute("href", `${ready.endpoint}/docs`);

    // Delete through the confirmation dialog.
    await endpoints.deleteButton(card).click();
    await endpoints.confirmDelete(DELETE_TIMEOUT);
    await expect(endpoints.toast("Item deleted successfully")).toBeVisible();
    await expect(card).toHaveCount(0);
    if ((await api.vectorDBInstances()).length === 0) {
      await expect(endpoints.emptyState).toBeVisible();
    }

    await expect
      .poll(async () => (await api.vectorDBInstances()).map((i) => i.id))
      .not.toContain(id);
    await waitForHelmReleaseGone(release);
    leftovers.length = 0;
  });
});
