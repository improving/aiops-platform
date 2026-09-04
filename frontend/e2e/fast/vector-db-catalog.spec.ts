import { test, expect, fixme } from "../fixtures";
import { VectorDBCatalogPage } from "../pages/vector-db-catalog";

test.describe("vector database catalog", () => {
  test("shows one card per seeded vector database", async ({ page, api }) => {
    const dbs = await api.vectorDBs();
    expect(dbs.map((d) => d.name).sort()).toEqual([
      "Chroma DB",
      "Milvus",
      "Qdrant",
    ]);

    const catalog = new VectorDBCatalogPage(page);
    await catalog.open();
    await expect(catalog.cards).toHaveCount(dbs.length);
    for (const db of dbs) {
      const card = catalog.card(db.name);
      await expect(card).toBeVisible();
      await expect(card.getByRole("button", { name: "Launch" })).toBeVisible();
    }
  });

  test("Launch opens the create dialog and Cancel closes it", async ({
    page,
  }) => {
    const catalog = new VectorDBCatalogPage(page);
    await catalog.open();
    await catalog.launch("Qdrant");

    const dialog = catalog.createDialog();
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Qdrant");
    await expect(dialog.getByRole("button", { name: "Create" })).toBeVisible();

    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
  });

  test("the create dialog offers a service type", async ({ page }) => {
    fixme(
      "the dialog has no service type control yet; ClusterIP/LoadBalancer select is pending"
    );
    const catalog = new VectorDBCatalogPage(page);
    await catalog.open();
    await catalog.launch("Qdrant");
    const select = catalog.serviceTypeSelect();
    await expect(select).toBeVisible();
    await select.click();
    await expect(page.getByRole("option", { name: "ClusterIP" })).toBeVisible();
    await expect(
      page.getByRole("option", { name: "LoadBalancer" })
    ).toBeVisible();
  });
});
