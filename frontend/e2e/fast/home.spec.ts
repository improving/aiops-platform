import { test, expect } from "../fixtures";
import { HomePage } from "../pages/home";

const cards = [
  {
    title: "Models",
    links: [
      {
        text: "View Catalog",
        href: "/models/catalog",
        heading: "Model Catalog",
      },
      {
        text: "View Instances",
        href: "/models/endpoints",
        heading: "Model Instances",
      },
    ],
  },
  {
    title: "Vector Databases",
    links: [
      {
        text: "View Catalog",
        href: "/vector-databases/catalog",
        heading: "Vector Database Catalog",
      },
      {
        text: "View Instances",
        href: "/vector-databases/endpoints",
        heading: "Vector Database Instances",
      },
    ],
  },
  {
    title: "Notebooks",
    links: [
      { text: "View Notebooks", href: "/notebooks", heading: "Notebooks" },
    ],
  },
  {
    title: "Develop",
    links: [
      {
        text: "Develop AI App",
        href: "/develop",
        heading: "Interactively Develop AI Applications",
      },
    ],
  },
];

test.describe("home page", () => {
  test("shows the four catalog cards with their links", async ({ page }) => {
    const home = new HomePage(page);
    await home.open();
    await expect(home.cards).toHaveCount(4);
    for (const card of cards) {
      await expect(home.card(card.title)).toBeVisible();
      for (const link of card.links) {
        await expect(home.cardLink(card.title, link.text)).toHaveAttribute(
          "href",
          link.href
        );
      }
    }
  });

  test("shows live counts for the organization", async ({ page, api }) => {
    const home = new HomePage(page);
    await home.open();
    await home.waitForLoaded();
    const instances = await api.inferenceInstances();
    const vectorDbs = await api.vectorDBInstances();
    const notebooks = await api.notebooks();
    await expect(home.stat("instances")).toContainText(
      `${instances.length} total`
    );
    await expect(home.stat("vectordbs")).toContainText(
      `${vectorDbs.length} total`
    );
    await expect(home.stat("notebooks")).toContainText(
      `${notebooks.length} total`
    );
    // providers.spec.ts adds and removes hosted models in parallel, so the
    // chat count can change between the page read and this API read.
    await expect(home.stat("chat")).toContainText(/\d+ ready/);
  });

  for (const card of cards) {
    for (const link of card.links) {
      test(`"${link.text}" on ${card.title} opens ${link.href}`, async ({
        page,
      }) => {
        const home = new HomePage(page);
        await home.open();
        await home.cardLink(card.title, link.text).click();
        await expect(page).toHaveURL(new RegExp(`${link.href}$`));
        await home.expectHeading(link.heading);
      });
    }
  }
});

test.describe("home page with a failing list", () => {
  test.use({
    allowedConsoleErrors: [
      /Failed to load resource|home overview: notebooks failed/,
    ],
  });

  test("shows unavailable on a tile whose list failed, without blanking the rest", async ({
    page,
  }) => {
    await page.route("**/api/v1alpha1/notebooks", (route) =>
      route.fulfill({ status: 503, json: { detail: "down" } })
    );
    const home = new HomePage(page);
    await home.open();
    await home.waitForLoaded();
    await expect(home.stat("notebooks")).toContainText("unavailable");
    await expect(home.stat("instances")).toContainText("0 total");
  });
});
