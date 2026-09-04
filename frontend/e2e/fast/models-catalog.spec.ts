import { test, expect } from "../fixtures";
import { ModelCatalogPage } from "../pages/model-catalog";

test.describe("model catalog", () => {
  test("lists every seeded model with Launch and Fine-tune actions", async ({
    page,
    api,
  }) => {
    const models = await api.models();
    const catalog = new ModelCatalogPage(page);
    await catalog.open();
    await expect(catalog.cards).toHaveCount(models.length);

    const first = models[0];
    const card = catalog.card(first.name);
    await expect(card).toContainText(first.modelId);
    await expect(card.getByRole("link", { name: "Launch" })).toHaveAttribute(
      "href",
      `/models/launch/${first.id}`
    );
    await expect(card.getByRole("link", { name: "Fine-tune" })).toHaveAttribute(
      "href",
      `/models/${first.id}/finetune`
    );
  });

  test("search narrows the cards and clearing restores them", async ({
    page,
    api,
  }) => {
    const models = await api.models();
    const matching = models.filter(
      (m) =>
        m.name.toLowerCase().includes("llama") ||
        m.modelId.toLowerCase().includes("llama")
    );
    expect(matching.length).toBeGreaterThan(0);
    expect(matching.length).toBeLessThan(models.length);

    const catalog = new ModelCatalogPage(page);
    await catalog.open();
    await expect(catalog.cards).toHaveCount(models.length);

    await catalog.search.fill("llama");
    await expect(catalog.cards).toHaveCount(matching.length);
    await expect(catalog.titleLinks()).toHaveText(matching.map((m) => m.name));

    await catalog.search.fill("no-such-model");
    await expect(catalog.cards).toHaveCount(0);

    await catalog.search.clear();
    await expect(catalog.cards).toHaveCount(models.length);
  });

  test("category and subcategory filters narrow the cards", async ({
    page,
    api,
  }) => {
    const models = await api.models();
    const embedding = models.filter((m) => m.category === "embedding");
    expect(embedding.length).toBeGreaterThan(0);

    const catalog = new ModelCatalogPage(page);
    await catalog.open();
    await expect(catalog.cards).toHaveCount(models.length);

    await catalog.selectCategory("embedding");
    await expect(catalog.cards).toHaveCount(embedding.length);
    await expect(catalog.titleLinks()).toHaveText(embedding.map((m) => m.name));

    // A subcategory that does not exist in this category empties the grid.
    await catalog.selectSubcategory("reranker");
    await expect(catalog.cards).toHaveCount(0);

    await catalog.selectSubcategory("All Subcategories");
    await expect(catalog.cards).toHaveCount(embedding.length);
    await catalog.selectCategory("All Categories");
    await expect(catalog.cards).toHaveCount(models.length);
  });

  test("search and category filter combine", async ({ page, api }) => {
    const models = await api.models();
    const expected = models.filter(
      (m) =>
        m.category === "llm" &&
        (m.name.toLowerCase().includes("phi") ||
          m.modelId.toLowerCase().includes("phi"))
    );
    expect(expected.length).toBeGreaterThan(0);

    const catalog = new ModelCatalogPage(page);
    await catalog.open();
    await catalog.selectCategory("llm");
    await catalog.search.fill("phi");
    await expect(catalog.cards).toHaveCount(expected.length);
  });

  test("Import Model opens a dialog that Cancel closes", async ({ page }) => {
    const catalog = new ModelCatalogPage(page);
    await catalog.open();
    await catalog.importButton.click();

    const dialog = catalog.dialog();
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByRole("heading", { name: "Import Model" })
    ).toBeVisible();
    await expect(dialog.getByPlaceholder("Model Name")).toBeVisible();
    await expect(dialog.getByPlaceholder("Model ID")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Import" })).toBeVisible();

    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toBeHidden();
  });

  test("a card title opens the model details", async ({ page, api }) => {
    const [first] = await api.models();
    const catalog = new ModelCatalogPage(page);
    await catalog.open();
    await catalog
      .card(first.name)
      .getByRole("link", { name: first.name })
      .click();
    await expect(page).toHaveURL(new RegExp(`/models/${first.id}$`));
    await catalog.expectHeading("Model Details");
  });
});
