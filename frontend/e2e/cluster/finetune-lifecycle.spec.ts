import { test, expect, shortId, kubernetesJobs } from "../fixtures";
import { FineTuneFormPage } from "../pages/finetune-form";
import { ModelDetailsPage } from "../pages/model-details";

const CREATE_TIMEOUT = 2 * 60_000;
const STATUS_TIMEOUT = 2 * 60_000;
const DELETE_TIMEOUT = 60_000;

test.describe("fine-tune lifecycle", { tag: "@cluster" }, () => {
  test.describe.configure({ mode: "serial" });

  const leftovers: { modelId: string; jobId: string }[] = [];

  test.afterEach(async ({ api }) => {
    for (const { modelId, jobId } of leftovers.splice(0)) {
      await api.deleteFineTuneJob(modelId, jobId);
    }
  });

  test("create a fine-tune job from the UI, see it in the cluster, then delete it", async ({
    page,
    api,
  }) => {
    const models = await api.models();
    const model = models.find((m) => m.category === "llm")!;
    const name = `e2e-ft-${shortId()}`;

    const form = new FineTuneFormPage(page);
    await form.open(model.id);
    await form.fillMinimal(name);
    await form.startButton.click();
    await expect(
      form.toast("Fine-tuning process started successfully")
    ).toBeVisible({ timeout: CREATE_TIMEOUT });
    await expect(page).toHaveURL(
      new RegExp(`/models/${model.id}\\?tab=finetune$`)
    );

    const job = (await api.fineTuneJobs(model.id)).find((j) => j.name === name);
    expect(job, `job ${name} exists in the API`).toBeTruthy();
    leftovers.push({ modelId: model.id, jobId: job!.id });
    const k8sJob = `finetune-job-${job!.id.slice(0, 8)}`;

    // The Fine-tune Jobs tab lists it and the Kubernetes Job exists.
    const details = new ModelDetailsPage(page);
    const row = details.jobRow(name);
    await expect(row).toBeVisible();
    await expect(row).toContainText(job!.id);
    expect(kubernetesJobs()).toContain(k8sJob);

    // The status comes from the cluster. There is no GPU here, so the pod
    // may never reach Running; require a cluster-derived status instead.
    await expect
      .poll(
        async () =>
          (await api.fineTuneJobs(model.id)).find((j) => j.id === job!.id)
            ?.status ?? "",
        { timeout: STATUS_TIMEOUT, intervals: [5_000] }
      )
      .toMatch(
        /Running|Pending|ContainerCreating|Failed|Error|BackOff|Succeeded/
      );
    await page.reload();
    await expect(row.getByRole("cell").nth(2)).not.toBeEmpty();

    // Delete through the confirmation dialog.
    await details.rowDeleteButton(row).click();
    await details.confirmDelete(DELETE_TIMEOUT);
    await expect(details.toast("Item deleted successfully")).toBeVisible();
    await expect(row).toHaveCount(0);

    await expect
      .poll(async () => (await api.fineTuneJobs(model.id)).map((j) => j.id))
      .not.toContain(job!.id);
    await expect
      .poll(() => kubernetesJobs(), {
        timeout: DELETE_TIMEOUT,
        intervals: [5_000],
      })
      .not.toContain(k8sJob);
    leftovers.length = 0;
  });
});
