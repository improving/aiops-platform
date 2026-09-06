import { test, expect } from "../fixtures";
import {
  VectorDBEndpointsPage,
  VectorDBInstanceDetailsPage,
} from "../pages/vector-db-endpoints";

function instance(i: number, ready: boolean) {
  return {
    id: `00000000-0000-0000-0000-${String(i).padStart(12, "0")}`,
    vectorDB: {
      id: "v",
      name: `db-${String(i).padStart(2, "0")}`,
      description: "",
      chart_name: "qdrant",
      chart_description: "",
    },
    configParams: {},
    endpoint: ready ? `http://vdb-${i}.example` : null,
    api_endpoint: null,
    ready,
    // Terminal, not "Pending": the mocked list must never look like it is
    // still deploying, or polling keeps re-fetching it in the background.
    status: ready ? "Running" : "Failed",
  };
}

const MOCK = Array.from({ length: 15 }, (_, i) => instance(i, i % 3 !== 0));

// The single-instance fetch for MOCK[0] reports it ready with an API
// endpoint, independent of the list mock (which keeps MOCK[0] not ready so
// the status filter/sort counts below stay simple to reason about).
const MOCK_0_READY = {
  ...MOCK[0],
  ready: true,
  status: "Running",
  endpoint: "http://vdb-0.example",
  api_endpoint: "https://vdb-0-api.example/",
};

test.describe("list controls", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1alpha1/vectordb_instances", (route) =>
      route.fulfill({ json: MOCK })
    );
    await page.route(
      `**/api/v1alpha1/vectordb_instances/${MOCK[0].id}`,
      (route) => route.fulfill({ json: MOCK_0_READY })
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
    await expect(list.cards).toHaveCount(12); // filter change resets to page 1

    await list.filterStatus("Ready");
    await expect(list.cards).toHaveCount(10);

    await list.filterStatus("All");
    await list.showMore.click();
    await expect(list.cards).toHaveCount(15);

    await list.sortBy("Name Z-A");
    await expect(list.cards.first()).toContainText("db-14");
    await list.sortBy("Name A-Z");
    await expect(list.cards.first()).toContainText("db-00");

    await list.sortBy("Status");
    await expect(list.cards.first()).toContainText("db-01");
    await list.sortBy("Name A-Z");

    await list.detailsLink(list.cards.first()).click();
    await expect(page).toHaveURL(
      /\/vector-databases\/endpoints\/00000000-0000-0000-0000-000000000000$/
    );
    await list.expectHeading("Vector Database Instance Details");

    const details = new VectorDBInstanceDetailsPage(page);
    await expect(details.field("Status")).toHaveText("Ready");
    await expect(details.field("Endpoint")).toContainText("vdb-0.example");
    await expect(details.copyButton("endpoint")).toBeVisible();
    await expect(details.copyButton("API endpoint")).toBeVisible();
    await expect(details.curlExample).toContainText("vdb-0-api.example");
  });

  test("a search term that matches nothing shows the empty state", async ({
    page,
  }) => {
    const list = new VectorDBEndpointsPage(page);
    await list.open();
    await list.waitForLoaded();
    await list.search.fill("no such instance");
    await expect(list.noMatch).toBeVisible();
    await expect(list.launchButton).toHaveCount(0);
  });
});
