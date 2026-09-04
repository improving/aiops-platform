import type { Page } from "@playwright/test";
import { test, expect, shortId, FAILED_RESOURCE, fixme } from "../fixtures";
import { FineTuneFormPage } from "../pages/finetune-form";
import { ModelDetailsPage } from "../pages/model-details";

/**
 * The TEST_MODE backend has no cluster, so it rejects the create call with
 * HTTP 500 (it tries to submit a Kubernetes Job). The submit -> list ->
 * delete -> logs flow is therefore exercised against stubbed responses that
 * mirror the real API shapes; the cluster tier runs the real thing.
 */
async function stubFineTuneApi(
  page: Page,
  modelId: string,
  job: { id: string; name: string }
) {
  const record = {
    id: job.id,
    name: job.name,
    status: "Created",
    params: { task: job.name, project_name: job.name },
    base_model: { id: modelId },
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  const jobs: (typeof record)[] = [];

  await page.route(
    `**/api/v1alpha1/models/${modelId}/finetune`,
    async (route) => {
      if (route.request().method() === "POST") {
        jobs.push(record);
        await route.fulfill({ status: 201, json: record });
        return;
      }
      await route.fulfill({ status: 200, json: jobs });
    }
  );
  await page.route(
    `**/api/v1alpha1/models/${modelId}/finetune/${job.id}`,
    async (route) => {
      if (route.request().method() === "DELETE") {
        jobs.length = 0;
        await route.fulfill({ status: 204 });
        return;
      }
      await route.fulfill({ status: 200, json: record });
    }
  );
  await page.route(
    `**/api/v1alpha1/models/${modelId}/finetune/${job.id}/logs`,
    async (route) => {
      // The real endpoint returns an object, not a bare string.
      await route.fulfill({
        status: 200,
        json: { logs: "step 1: loading dataset\nstep 2: training" },
      });
    }
  );
}

test.describe("fine-tune form", () => {
  test("shows the config, dataset and hyperparameter sections", async ({
    page,
    api,
  }) => {
    const [model] = await api.models();
    const form = new FineTuneFormPage(page);
    await form.open(model.id);
    await form.expectHeading("Fine-tune Model");
    await expect(page.getByText("Fine-tune Config")).toBeVisible();
    await expect(page.getByText("Dataset", { exact: true })).toBeVisible();
    await expect(page.getByText("Hyperparameters")).toBeVisible();
    await expect(form.importConfigButton).toBeVisible();
    await expect(page.getByLabel("Epochs")).toHaveValue("2");
    await expect(page.getByLabel("Lora R")).toHaveValue("16");
  });

  test("an empty submit is blocked by validation", async ({ page, api }) => {
    const [model] = await api.models();
    const form = new FineTuneFormPage(page);
    await form.open(model.id);

    const posts: string[] = [];
    page.on("request", (req) => {
      if (req.method() === "POST") posts.push(req.url());
    });

    await form.startButton.click();
    expect(
      await form.name.evaluate((el: HTMLInputElement) => el.checkValidity())
    ).toBe(false);
    expect(
      await form.name.evaluate((el: HTMLInputElement) => el.validationMessage)
    ).not.toBe("");
    await expect(page).toHaveURL(new RegExp(`/models/${model.id}/finetune$`));
    expect(posts).toEqual([]);
  });

  test.describe("against the TEST_MODE backend", () => {
    // The rejected POST is logged by Chromium as a failed resource.
    test.use({ allowedConsoleErrors: [FAILED_RESOURCE] });

    test("the backend rejects the job and the form shows the error toast", async ({
      page,
      api,
    }) => {
      const [model] = await api.models();
      const form = new FineTuneFormPage(page);
      await form.open(model.id);
      await form.fillMinimal(`e2e-ft-${shortId()}`);
      await form.startButton.click();

      await expect(form.toast(/API Error/)).toBeVisible();
      await expect(form.toast(/HTTP 500/)).toBeVisible();
      await expect(page).toHaveURL(new RegExp(`/models/${model.id}/finetune$`));
      expect(await api.fineTuneJobs(model.id)).toEqual([]);
    });
  });

  test.describe("with a stubbed job API", () => {
    test("a valid submission creates a job that appears in the Fine-tune Jobs tab and can be deleted", async ({
      page,
      api,
    }) => {
      const [model] = await api.models();
      const job = {
        id: "11111111-2222-4333-8444-555555555555",
        name: `e2e-ft-${shortId()}`,
      };
      await stubFineTuneApi(page, model.id, job);

      const form = new FineTuneFormPage(page);
      await form.open(model.id);
      await form.fillMinimal(job.name);
      await form.startButton.click();

      await expect(
        form.toast("Fine-tuning process started successfully")
      ).toBeVisible();
      await expect(page).toHaveURL(
        new RegExp(`/models/${model.id}\\?tab=finetune$`)
      );

      const details = new ModelDetailsPage(page);
      await expect(details.tab("Fine-tune Jobs")).toHaveAttribute(
        "aria-selected",
        "true"
      );
      const row = details.jobRow(job.name);
      await expect(row).toBeVisible();
      await expect(row).toContainText("Created");

      await details.jobParamsButton(row).click();
      const paramsDialog = details
        .dialog()
        .filter({ hasText: "Fine-tune Job Parameters" });
      await expect(paramsDialog).toBeVisible();
      await expect(paramsDialog).toContainText(`project_name: ${job.name}`);
      await page.keyboard.press("Escape");
      await expect(paramsDialog).toBeHidden();

      await details.rowDeleteButton(row).click();
      await details.confirmDelete();
      await expect(details.toast("Item deleted successfully")).toBeVisible();
      await expect(row).toHaveCount(0);
    });

    test("the Logs button opens the logs dialog without crashing", async ({
      page,
      api,
    }) => {
      fixme("the logs response is an object and rendering it crashes the page");
      const [model] = await api.models();
      const job = {
        id: "11111111-2222-4333-8444-555555555555",
        name: `e2e-ft-${shortId()}`,
      };
      await stubFineTuneApi(page, model.id, job);

      const form = new FineTuneFormPage(page);
      await form.open(model.id);
      await form.fillMinimal(job.name);
      await form.startButton.click();

      const details = new ModelDetailsPage(page);
      const row = details.jobRow(job.name);
      await expect(row).toBeVisible();

      await details.jobLogsButton(row).click();
      const logsDialog = details
        .dialog()
        .filter({ hasText: "Fine-tune Job Logs" });
      await expect(logsDialog).toBeVisible();
      await expect(logsDialog).toContainText("step 1: loading dataset");
    });
  });
});
