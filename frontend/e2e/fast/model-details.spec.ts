import { test, expect, FAILED_RESOURCE, fixme } from "../fixtures";
import { ModelDetailsPage } from "../pages/model-details";

test.describe("model details", () => {
  test("shows the model fields and actions on the Details tab", async ({
    page,
    api,
  }) => {
    const [model] = await api.models();
    const details = new ModelDetailsPage(page);
    await details.open(model.id);

    await expect(details.tab("Details")).toHaveAttribute(
      "aria-selected",
      "true"
    );
    const panel = details.panel();
    await expect(panel).toContainText(model.name);
    await expect(panel).toContainText(model.modelId);
    await expect(panel).toContainText(model.category);
    await expect(
      panel.getByRole("button", { name: "Launch Model" })
    ).toBeVisible();
    await expect(
      panel.getByRole("link", { name: "Fine-tune" })
    ).toHaveAttribute("href", `/models/${model.id}/finetune`);
  });

  test("the selected tab is reflected in ?tab= and survives a reload", async ({
    page,
    api,
  }) => {
    const [model] = await api.models();
    const details = new ModelDetailsPage(page);
    await details.open(model.id);

    await details.tab("Adapters").click();
    await expect(page).toHaveURL(
      new RegExp(`/models/${model.id}\\?tab=adapters$`)
    );
    await expect(details.tab("Adapters")).toHaveAttribute(
      "aria-selected",
      "true"
    );
    await expect(
      details.panel().getByRole("button", { name: "Import Adapter" })
    ).toBeVisible();

    await page.reload();
    await expect(details.tab("Adapters")).toHaveAttribute(
      "aria-selected",
      "true"
    );

    await details.tab("Fine-tune Jobs").click();
    await expect(page).toHaveURL(new RegExp(`\\?tab=finetune$`));
    await expect(details.table()).toBeVisible();

    await page.reload();
    await expect(details.tab("Fine-tune Jobs")).toHaveAttribute(
      "aria-selected",
      "true"
    );
  });

  test("a ?tab= deep link opens that tab", async ({ page, api }) => {
    const [model] = await api.models();
    const details = new ModelDetailsPage(page);
    await details.open(model.id, "finetune");
    await expect(details.tab("Fine-tune Jobs")).toHaveAttribute(
      "aria-selected",
      "true"
    );
    await expect(
      details.table().getByRole("columnheader", { name: "Status" })
    ).toBeVisible();
  });

  test.describe("Launch Model", () => {
    // The launch page asks for hosts, which the TEST_MODE backend cannot list.
    test.use({ allowedConsoleErrors: [FAILED_RESOURCE] });

    test("navigates to the launch wizard", async ({ page, api }) => {
      const [model] = await api.models();
      const details = new ModelDetailsPage(page);
      await details.open(model.id);
      await details
        .panel()
        .getByRole("button", { name: "Launch Model" })
        .click();
      await expect(page).toHaveURL(new RegExp(`/models/launch/${model.id}$`));
      await details.expectHeading("Launch Model");
    });
  });

  test("empty Adapters and Fine-tune Jobs tables show an empty-state row", async ({
    page,
    api,
  }) => {
    fixme("empty tables render no rows today; an empty-state row is pending");
    const [model] = await api.models();
    const details = new ModelDetailsPage(page);

    await details.open(model.id, "adapters");
    await expect(details.bodyRows()).toHaveCount(1);
    await expect(details.bodyRows().first()).toContainText(/no adapters/i);

    await details.tab("Fine-tune Jobs").click();
    await expect(details.bodyRows()).toHaveCount(1);
    await expect(details.bodyRows().first()).toContainText(
      /no fine-tune jobs/i
    );
  });
});
