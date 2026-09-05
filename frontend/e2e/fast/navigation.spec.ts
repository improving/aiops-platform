import { test, expect } from "../fixtures";
import { AppShell } from "../pages/app-shell";

const pages = [
  { path: "/", heading: "Welcome to AI Hub" },
  { path: "/notebooks", heading: "Notebooks" },
  { path: "/models/catalog", heading: "Model Catalog" },
  { path: "/models/endpoints", heading: "Inference Endpoints" },
  { path: "/vector-databases/catalog", heading: "Vector Database Catalog" },
  {
    path: "/vector-databases/endpoints",
    heading: "Vector Databases Endpoints",
  },
  { path: "/develop", heading: "Interactively Develop AI Applications" },
  { path: "/notebooks/new", heading: "Create New Notebook" },
  { path: "/chat", heading: "Chat" },
];

test.describe("header navigation", () => {
  test("top-level links navigate to their pages", async ({ page }) => {
    const shell = new AppShell(page);
    await shell.goto("/");
    await shell.expectHeading("Welcome to AI Hub");

    await shell.navLink("Notebooks").click();
    await expect(page).toHaveURL(/\/notebooks$/);
    await shell.expectHeading("Notebooks");

    await shell.navLink("Develop").click();
    await expect(page).toHaveURL(/\/develop$/);
    await shell.expectHeading("Interactively Develop AI Applications");
  });

  test("Models dropdown items navigate to catalog and instances", async ({
    page,
  }) => {
    const shell = new AppShell(page);
    await shell.goto("/");

    await shell.clickDropdownItem("Models", "Catalog");
    await expect(page).toHaveURL(/\/models\/catalog$/);
    await shell.expectHeading("Model Catalog");

    await shell.clickDropdownItem("Models", "Instances");
    await expect(page).toHaveURL(/\/models\/endpoints$/);
    await shell.expectHeading("Inference Endpoints");
  });

  test("Vector Databases dropdown items navigate to catalog and instances", async ({
    page,
  }) => {
    const shell = new AppShell(page);
    await shell.goto("/");

    await shell.clickDropdownItem("Vector Databases", "Catalog");
    await expect(page).toHaveURL(/\/vector-databases\/catalog$/);
    await shell.expectHeading("Vector Database Catalog");

    await shell.clickDropdownItem("Vector Databases", "Instances");
    await expect(page).toHaveURL(/\/vector-databases\/endpoints$/);
    await shell.expectHeading("Vector Databases Endpoints");
  });

  test("the brand link returns home", async ({ page }) => {
    const shell = new AppShell(page);
    await shell.goto("/models/catalog");
    await shell.navigateByClick(shell.brand, /\/$/);
    await shell.expectHeading("Welcome to AI Hub");
  });

  test("the active section is highlighted", async ({ page }) => {
    const shell = new AppShell(page);
    await shell.goto("/models/catalog");
    await expect(shell.navTrigger("Models")).toHaveClass(/font-bold/);
    await expect(shell.navLink("Notebooks")).not.toHaveClass(/font-bold/);
  });

  test("the footer shows the current year", async ({ page }) => {
    const shell = new AppShell(page);
    await shell.goto("/");
    await expect(shell.footer).toContainText(String(new Date().getFullYear()));
  });
});

test.describe("every page renders without console errors", () => {
  for (const { path, heading } of pages) {
    test(`${path} shows "${heading}"`, async ({ page, consoleErrors }) => {
      const shell = new AppShell(page);
      await shell.goto(path);
      await shell.expectHeading(heading);
      // Wait for the client-side fetches to render, then give late errors a
      // moment to surface before the console guard runs.
      await expect(page.getByText("Loading...")).toHaveCount(0);
      await page.waitForTimeout(500);
      expect(consoleErrors).toEqual([]);
    });
  }
});
