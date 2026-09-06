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
