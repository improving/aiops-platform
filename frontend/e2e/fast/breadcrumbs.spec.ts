import { test, expect } from "../fixtures";
import { AppShell } from "../pages/app-shell";

test.describe("breadcrumbs", () => {
  test("the new notebook page links back to Notebooks", async ({ page }) => {
    const shell = new AppShell(page);
    await shell.goto("/notebooks/new");
    const trail = shell.breadcrumbs();
    await expect(trail).toBeVisible();
    await expect(trail.getByRole("link", { name: "Home" })).toHaveAttribute(
      "href",
      "/"
    );
    await expect(
      trail.getByRole("link", { name: "Notebooks" })
    ).toHaveAttribute("href", "/notebooks");
    await expect(trail.getByText("New")).toBeVisible();
    await shell.navigateByClick(
      trail.getByRole("link", { name: "Notebooks" }),
      /\/notebooks$/
    );
    await shell.expectHeading("Notebooks");
  });

  test("a model page links back to the catalog", async ({ page, api }) => {
    const [model] = await api.models();
    const shell = new AppShell(page);
    await shell.goto(`/models/${model.id}`);
    const trail = shell.breadcrumbs();
    await expect(trail.getByRole("link", { name: "Catalog" })).toHaveAttribute(
      "href",
      "/models/catalog"
    );
    await expect(trail.getByText(model.name)).toBeVisible();
  });

  test("list pages have no breadcrumbs", async ({ page }) => {
    const shell = new AppShell(page);
    await shell.goto("/notebooks");
    await expect(shell.breadcrumbs()).toHaveCount(0);
  });
});
