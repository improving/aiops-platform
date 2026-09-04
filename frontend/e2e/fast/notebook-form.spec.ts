import { test, expect, fixme } from "../fixtures";
import { NotebookFormPage } from "../pages/notebook-form";

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
    // Nothing changed yet, so there is nothing to launch.
    await expect(form.launchButton).toBeDisabled();
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

  test("an empty name is rejected", async ({ page }) => {
    const form = new NotebookFormPage(page);
    await form.open();
    await form.cpu.fill("1");
    await expect(form.launchButton).toBeEnabled();

    const posts: string[] = [];
    page.on("request", (req) => {
      if (req.method() === "POST") posts.push(req.url());
    });
    await form.launchButton.click();
    await expect(page.getByText("Name is required")).toBeVisible();
    await expect(page).toHaveURL(/\/notebooks\/new$/);
    expect(posts).toEqual([]);
  });

  test("a name that is not a valid resource name is rejected", async ({
    page,
  }) => {
    fixme("the name has no format validation yet; a DNS-label rule is pending");
    const form = new NotebookFormPage(page);
    await form.open();
    await form.name.fill("Invalid Name!");
    await form.launchButton.click();
    await expect(page.getByText(/lowercase|letters|hyphen/i)).toBeVisible();
    await expect(page).toHaveURL(/\/notebooks\/new$/);
  });

  test("out-of-range resources are rejected", async ({ page }) => {
    const form = new NotebookFormPage(page);
    await form.open();
    await form.name.fill("e2e-range");
    await form.storage.fill("50");
    const posts: string[] = [];
    page.on("request", (req) => {
      if (req.method() === "POST") posts.push(req.url());
    });
    await form.launchButton.click();
    // The input's max attribute stops the submit in the browser.
    expect(
      await form.storage.evaluate((el: HTMLInputElement) => el.checkValidity())
    ).toBe(false);
    await expect(page).toHaveURL(/\/notebooks\/new$/);
    expect(posts).toEqual([]);
  });

  test("the storage field explains its range", async ({ page }) => {
    fixme("the storage field has no helper text yet");
    const form = new NotebookFormPage(page);
    await form.open();
    const description = await form.description(form.storage);
    await expect(description).toBeVisible();
    await expect(description).toContainText(/5.*20/);
  });
});
