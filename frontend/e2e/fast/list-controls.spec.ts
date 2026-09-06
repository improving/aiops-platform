import { test, expect, FAILED_RESOURCE } from "../fixtures";
import { VectorDBEndpointsPage } from "../pages/vector-db-endpoints";

function instance(i: number, ready: boolean) {
  return {
    id: `00000000-0000-0000-0000-${String(i).padStart(12, "0")}`,
    vectorDB: { id: "v", name: `db-${String(i).padStart(2, "0")}`, description: "", chart_name: "qdrant", chart_description: "" },
    configParams: {},
    endpoint: ready ? `http://vdb-${i}.example` : null,
    api_endpoint: null,
    ready,
    status: ready ? "Running" : "Pending",
  };
}

const MOCK = Array.from({ length: 15 }, (_, i) => instance(i, i % 3 !== 0));

test.describe("list controls", () => {
  // The card-title click-through below opens the detail page for a mocked
  // id the fast backend does not know, so that fetch 404s.
  test.use({ allowedConsoleErrors: [FAILED_RESOURCE] });

  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1alpha1/vectordb_instances", (route) =>
      route.fulfill({ json: MOCK })
    );
  });

  test("pages, filters by status and sorts by name", async ({ page }) => {
    const list = new VectorDBEndpointsPage(page);
    await list.open();
    await list.waitForLoaded();
    await expect(list.cards).toHaveCount(12);
    await expect(list.showMore).toContainText("12 of 15");
    await list.showMore.click();
    await expect(list.cards).toHaveCount(15);

    await list.filterStatus("Not ready");
    await expect(list.cards).toHaveCount(5);
    await list.filterStatus("All");

    await list.sortBy("Name Z-A");
    await expect(list.cards.first()).toContainText("db-14");
    await list.sortBy("Name A-Z");
    await expect(list.cards.first()).toContainText("db-00");

    await list.detailsLink(list.cards.first()).click();
    await expect(page).toHaveURL(
      /\/vector-databases\/endpoints\/00000000-0000-0000-0000-000000000000$/
    );
    await list.expectHeading("Vector Database Instance Details");
  });
});
