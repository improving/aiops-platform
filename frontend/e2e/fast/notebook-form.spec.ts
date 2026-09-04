import { test, expect } from "../fixtures";
import { NotebookFormPage } from "../pages/notebook-form";
import { FAILED_RESOURCE } from "../fixtures";

test.describe("new notebook form", () => {
  test("has the Jupyter defaults", async ({ page }) => {
    const form = new NotebookFormPage(page);
    await form.open();
    await expect(form.type).toContainText("Jupyter");
    await expect(form.framework).toContainText("PyTorch");
    await expect(form.cpu).toHaveValue("0.5");
    await expect(form.memory).toHaveValue("1");
    await expect(form.storage).toHaveValue("5");
    await expect(form.gpuSwitch).not.toBeChecked();
    await expect(form.gpuCount).toHaveCount(0);
    // Launch is enabled until a field reports an error.
    await expect(form.launchButton).toBeEnabled();
  });

  test("switching to VS Code hides framework and GPU", async ({ page }) => {
    const form = new NotebookFormPage(page);
    await form.open();
    await expect(form.framework).toBeVisible();
    await expect(form.gpuSwitch).toBeVisible();

    await form.selectType("VSCode");
    await expect(form.framework).toHaveCount(0);
    await expect(form.gpuSwitch).toHaveCount(0);
    await expect(form.gpuCount).toHaveCount(0);

    await form.selectType("Jupyter");
    await expect(form.framework).toBeVisible();
    await expect(form.gpuSwitch).toBeVisible();
  });

  test("enabling the GPU reveals the GPU count", async ({ page }) => {
    const form = new NotebookFormPage(page);
    await form.open();
    await form.gpuSwitch.click();
    await expect(form.gpuSwitch).toBeChecked();
    await expect(form.gpuCount).toBeVisible();
    await expect(form.gpuCount).toHaveValue("1");
    await form.gpuSwitch.click();
    await expect(form.gpuCount).toHaveCount(0);
  });

  test("an empty name keeps Launch disabled", async ({ page }) => {
    const form = new NotebookFormPage(page);
    await form.open();
    await form.name.fill("a");
    await form.name.fill("");
    await expect(page.getByText("Name is required")).toBeVisible();
    await expect(form.launchButton).toBeDisabled();
    await expect(page).toHaveURL(/\/notebooks\/new$/);
  });

  test("a name that is not a valid resource name is rejected", async ({
    page,
  }) => {
    const form = new NotebookFormPage(page);
    await form.open();
    await form.name.fill("Invalid Name!");
    await expect(
      page.getByText(/lowercase|letters|hyphen/i).first()
    ).toBeVisible();
    await expect(form.launchButton).toBeDisabled();
    await expect(page).toHaveURL(/\/notebooks\/new$/);
  });

  test("out-of-range resources are rejected", async ({ page }) => {
    const form = new NotebookFormPage(page);
    await form.open();
    await form.name.fill("e2e-range");
    await form.storage.fill("50");
    // Both the schema and the input's max attribute reject the value.
    expect(
      await form.storage.evaluate((el: HTMLInputElement) => el.checkValidity())
    ).toBe(false);
    await expect(form.launchButton).toBeDisabled();
    await expect(page).toHaveURL(/\/notebooks\/new$/);
  });

  test.describe("backend responses", () => {
    // The browser logs a failed resource for the stubbed 4xx responses.
    test.use({ allowedConsoleErrors: [FAILED_RESOURCE] });

    test("a duplicate name surfaces the backend 409 message", async ({
      page,
    }) => {
      await page.route("**/api/v1alpha1/notebooks", (route) =>
        route.request().method() === "POST"
          ? route.fulfill({
              status: 409,
              contentType: "application/json",
              body: JSON.stringify({
                detail: "Notebook 'e2e-dup' already exists",
              }),
            })
          : route.continue()
      );
      const form = new NotebookFormPage(page);
      await form.open();
      await form.name.fill("e2e-dup");
      await expect(form.launchButton).toBeEnabled();
      await form.launchButton.click();
      await expect(form.toast(/already exists/)).toBeVisible();
      await expect(page).toHaveURL(/\/notebooks\/new$/);
    });

    test("a backend validation error is shown in the toast", async ({
      page,
    }) => {
      await page.route("**/api/v1alpha1/notebooks", (route) =>
        route.request().method() === "POST"
          ? route.fulfill({
              status: 422,
              contentType: "application/json",
              body: JSON.stringify({
                detail: [
                  {
                    loc: ["body", "name"],
                    msg: "Value error, must be lowercase letters, digits and '-'",
                    type: "value_error",
                  },
                ],
              }),
            })
          : route.continue()
      );
      const form = new NotebookFormPage(page);
      await form.open();
      await form.name.fill("e2e-valid-name");
      await expect(form.launchButton).toBeEnabled();
      await form.launchButton.click();
      await expect(form.toast(/lowercase letters/)).toBeVisible();
    });
  });

  test("the storage field explains its range", async ({ page }) => {
    const form = new NotebookFormPage(page);
    await form.open();
    const description = await form.description(form.storage);
    await expect(description).toBeVisible();
    await expect(description).toContainText(/5.*20/);
  });
});
