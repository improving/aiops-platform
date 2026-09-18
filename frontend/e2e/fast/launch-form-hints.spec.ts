import type { Page } from "@playwright/test";
import { test, expect } from "../fixtures";
import { LaunchModelPage } from "../pages/launch-model";

// The hints of the launch wizard: what is free on the picked host, whether
// the weights fit its GPU, and the info buttons of known arguments. Unlike
// launch-form.spec.ts, GET /hosts is stubbed here (the TEST_MODE backend has
// no cluster), so no "API Error" toast and no allowed console error.

const GIB = 1024 * 1024 * 1024;

function host(overrides: Record<string, unknown> = {}) {
  return {
    hostname: "gpu-node",
    cpu_vendor: "Intel",
    cpu_memory: 0,
    cpu_cores: 0,
    cuda_driver_version: "595.71.05",
    cuda_runtime_version: "13.2",
    gpu_count: 1,
    gpu_memory: 24564,
    gpu_model: "NVIDIA-GeForce-RTX-4090",
    gpu_replicas: 1,
    gpu_sharing_strategy: "N/A",
    gpu_usage: 0,
    allocatable_cpu: 32,
    allocatable_memory: 128 * 1024,
    allocatable_gpu: 1,
    requested_cpu: 4,
    requested_memory: 8 * 1024,
    ...overrides,
  };
}

async function openWith(
  page: Page,
  launch: LaunchModelPage,
  modelId: string,
  hosts: unknown[]
) {
  await page.route("**/api/v1alpha1/hosts", (route) =>
    route.fulfill({ json: hosts })
  );
  await Promise.all([
    page.waitForResponse((res) => res.url().includes("/api/v1alpha1/hosts")),
    launch.open(modelId),
  ]);
  await launch.expectHeading("Launch Model");
}

/** An LLM with a vLLM serving option and a known size in the seed catalog. */
async function sizedLlm(api: {
  models: () => Promise<
    { id: string; category: string; size?: number | null; name: string }[]
  >;
}) {
  const model = (await api.models()).find(
    (m) => m.category === "llm" && m.name === "Qwen2 7B Instruct"
  );
  expect(model, "the seed catalog has Qwen2 7B Instruct").toBeTruthy();
  expect(model!.size).toBe(15 * GIB);
  return model!;
}

test.describe("launch wizard hints", () => {
  test("a picked host shows what is free and that the weights fit", async ({
    page,
    api,
  }) => {
    const model = await sizedLlm(api);
    const launch = new LaunchModelPage(page);
    await openWith(page, launch, model.id, [host()]);

    const card = page
      .locator('main [data-slot="card"]')
      .filter({ hasText: "Host: gpu-node" })
      // The step's own card contains the host card: take the inner one.
      .last();
    await expect(card).toContainText("28 of 32 CPU free");
    await expect(card).toContainText("120 of 128 GiB memory free");
    await expect(card).toContainText("1 GPU free");
    await card.click();
    await launch.nextButton.click();
    await launch.selectEngine("vLLM");

    await expect(page.locator("#gpu-hint")).toContainText(
      "1 of 1 GPUs free on gpu-node"
    );
    const fit = page.locator('[data-slot="gpu-fit"]');
    await expect(fit).toHaveAttribute("role", "status");
    await expect(fit).toContainText("Weights about 15 GiB of 24 GiB");
    await expect(fit).toContainText("About 5.3 GiB stays for the KV cache");

    // Free numbers show before anything is typed; asking for more than is
    // free warns in place, and never blocks the launch.
    await expect(page.locator("#cpu-hint")).toContainText(
      "28 of 32 CPU cores free on gpu-node"
    );
    await launch.cpuInput.fill("30");
    await expect(page.locator("#cpu-hint").getByRole("alert")).toContainText(
      "More than is free"
    );
    await launch.cpuInput.fill("4");
    await expect(page.locator("#cpu-hint").getByRole("alert")).toHaveCount(0);
    await launch.memoryInput.fill("200Gi");
    await expect(page.locator("#memory-hint").getByRole("alert")).toContainText(
      "120 of 128 GiB memory free"
    );
    await expect(launch.nextButton).toBeEnabled();
  });

  test("a busy GPU and weights that do not fit warn before the launch", async ({
    page,
    api,
  }) => {
    const model = await sizedLlm(api);
    const launch = new LaunchModelPage(page);
    await openWith(page, launch, model.id, [
      host({ gpu_memory: 8192, gpu_usage: 1, gpu_model: "NVIDIA-T4" }),
    ]);

    const card = page
      .locator('main [data-slot="card"]')
      .filter({ hasText: "Host: gpu-node" })
      // The step's own card contains the host card: take the inner one.
      .last();
    await expect(card).toContainText("GPU in use");
    await card.click();
    await launch.nextButton.click();
    await launch.selectEngine("vLLM");

    await expect(page.locator("#gpu-hint").getByRole("alert")).toContainText(
      "waits as Pending until a GPU is free"
    );
    const fit = page.locator('[data-slot="gpu-fit"]');
    await expect(fit).toHaveAttribute("role", "alert");
    await expect(fit).toContainText("The weights do not fit");
    // A hint, not a gate.
    await expect(launch.nextButton).toBeEnabled();
  });

  test("without a host the form shows no capacity hint", async ({
    page,
    api,
  }) => {
    const model = await sizedLlm(api);
    const launch = new LaunchModelPage(page);
    await openWith(page, launch, model.id, [host()]);
    await launch.skipButton.click();
    await launch.selectEngine("vLLM");
    await expect(page.locator('[data-slot="resource-hint"]')).toHaveCount(0);
    await expect(page.locator('[data-slot="gpu-fit"]')).toHaveCount(0);
    // The static help is always there.
    await expect(page.locator("#cpu-help")).toContainText("for example 4");
  });

  test("known arguments and variables carry an info button", async ({
    page,
    api,
  }) => {
    const model = await sizedLlm(api);
    const vllm = (await api.engines()).find((e) => e.name === "vLLM")!;
    const launch = new LaunchModelPage(page);
    await openWith(page, launch, model.id, [host()]);
    await launch.skipButton.click();
    await launch.selectEngine("vLLM");
    await launch.nextButton.click();

    // The buttons add no row: the seeded rows are what they were.
    await expect(launch.argNames).toHaveCount(vllm.default_args.length);
    await expect(launch.envNames).toHaveCount(vllm.default_config.length);

    await page.getByRole("button", { name: "About max_model_len" }).click();
    const help = page.locator('[data-slot="popover-content"]');
    await expect(help).toContainText("prompt plus answer, in tokens");
    await expect(help).toContainText("Default:");
    await expect(help).toContainText("Range:");
    await page.keyboard.press("Escape");

    await page.getByRole("button", { name: "About HF_HUB_OFFLINE" }).click();
    await expect(help).toContainText("forbids every download");
    await page.keyboard.press("Escape");

    // A name the catalog does not know has no button; a known one typed
    // into a new row gets it, whatever its spelling.
    await launch.addArgumentButton.click();
    await launch.argNames.last().fill("--my-own-flag");
    await expect(
      page.getByRole("button", { name: /About .*my-own-flag/ })
    ).toHaveCount(0);
    await launch.argNames.last().fill("gpu_memory_utilization");
    await expect(
      page.getByRole("button", { name: "About --gpu-memory-utilization" })
    ).toBeVisible();
    // The structural "Delete" locator of the page object still finds one.
    await expect(launch.lastArgDeleteButton()).toHaveCount(1);
  });
});
