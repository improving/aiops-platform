import type { Page } from "@playwright/test";
import { test, expect, FAILED_RESOURCE } from "../fixtures";
import { LaunchModelPage } from "../pages/launch-model";

// The TEST_MODE backend has no cluster: GET /hosts answers 500, which the
// page reports with an "API Error" toast and an empty accelerator list.
test.use({ allowedConsoleErrors: [FAILED_RESOURCE] });

/**
 * Open the wizard and wait for the hosts request to finish. It fails without
 * a cluster and raises a toast; the toaster shows one toast at a time, so a
 * late failure would replace the toast a test is asserting on.
 */
async function openLaunch(
  page: Page,
  launch: LaunchModelPage,
  modelId: string
) {
  await Promise.all([
    page.waitForResponse((res) => res.url().includes("/api/v1alpha1/hosts")),
    launch.open(modelId),
  ]);
  await expect(launch.toast(/API Error/)).toBeVisible();
}

async function firstLlm(api: {
  models: () => Promise<{ id: string; category: string }[]>;
}) {
  const models = await api.models();
  const llm = models.find((m) => m.category === "llm");
  expect(llm, "the catalog should contain an LLM").toBeTruthy();
  return llm!;
}

test.describe("launch wizard", () => {
  test("walks through accelerators, deploy config and env vars", async ({
    page,
    api,
  }) => {
    const model = await firstLlm(api);
    const engines = await api.engines();
    const vllm = engines.find((e) => e.name === "vLLM")!;

    const launch = new LaunchModelPage(page);
    await openLaunch(page, launch, model.id);
    await launch.expectHeading("Launch Model");

    // Step 1: accelerators. No hosts without a cluster, so Next is blocked
    // and Skip lets the backend pick one.
    await expect(launch.tab("Accelerators")).toHaveAttribute(
      "aria-selected",
      "true"
    );
    await expect(launch.tab("Deploy Config")).toBeDisabled();
    await expect(launch.tab("CLI Args and Env Variables")).toBeDisabled();
    await launch.nextButton.click();
    await expect(launch.toast("Host Selection Required")).toBeVisible();
    await launch.skipButton.click();
    await expect(launch.tab("Deploy Config")).toHaveAttribute(
      "aria-selected",
      "true"
    );

    // Step 2: deploy config needs an engine.
    await launch.nextButton.click();
    await expect(launch.toast("Engine Selection Required")).toBeVisible();
    await launch.selectEngine("vLLM");
    await expect(launch.tracingSwitch).toBeVisible();
    await launch.nextButton.click();

    // Step 3: args and env vars are pre-filled from the engine defaults.
    await expect(launch.tab("CLI Args and Env Variables")).toHaveAttribute(
      "aria-selected",
      "true"
    );
    await expect(launch.argNames).toHaveCount(vllm.default_args.length);
    await expect(launch.envNames).toHaveCount(vllm.default_config.length);
    await expect(launch.argNames.first()).toHaveValue(
      vllm.default_args[0].name
    );
    await expect(launch.createButton).toBeVisible();
  });

  test("only launchable serving options are offered for an LLM", async ({
    page,
    api,
  }) => {
    const model = await firstLlm(api);
    // The engine Select renders the model's own serving options
    // (GET /models/{id}/serving-options), in that order, filtered to the
    // ones with an engine_id (a hosted option has none and no chart to
    // launch); Ollama is llm_support too, but a Hugging Face id's catalog
    // row has no Ollama serving option (see "a Hugging Face id offers
    // HuggingFace, vLLM and NIM" below).
    const options = await api.servingOptions(model.id);
    const expected = options.filter((o) => o.engine_id).map((o) => o.engine);
    expect(expected.length).toBeGreaterThan(0);

    const launch = new LaunchModelPage(page);
    await openLaunch(page, launch, model.id);
    await launch.skipButton.click();
    await launch.engineSelect.click();
    await expect(page.getByRole("option")).toHaveText(expected);
    await page.keyboard.press("Escape");
  });

  test("an argument with an empty name blocks the submit", async ({
    page,
    api,
  }) => {
    const model = await firstLlm(api);
    const launch = new LaunchModelPage(page);
    await openLaunch(page, launch, model.id);
    await launch.skipButton.click();
    await launch.selectEngine("vLLM");
    await launch.nextButton.click();

    const before = await launch.argNames.count();
    await launch.addArgumentButton.click();
    await expect(launch.argNames).toHaveCount(before + 1);
    const added = launch.argNames.last();
    await expect(added).toHaveValue("");
    await expect(added).toBeEditable();

    const posts: string[] = [];
    page.on("request", (req) => {
      if (req.method() === "POST") posts.push(req.url());
    });
    await launch.createButton.click();
    expect(
      await added.evaluate((el: HTMLInputElement) => el.checkValidity())
    ).toBe(false);
    expect(posts).toEqual([]);

    await launch.lastArgDeleteButton().click();
    await expect(launch.argNames).toHaveCount(before);
  });

  test("a rejected deploy shows an error toast", async ({ page, api }) => {
    const model = await firstLlm(api);
    const launch = new LaunchModelPage(page);
    await openLaunch(page, launch, model.id);
    await launch.skipButton.click();
    await launch.selectEngine("vLLM");
    await launch.nextButton.click();

    const [response] = await Promise.all([
      page.waitForResponse(
        (res) =>
          res.url().includes("/inferenceInstance") &&
          res.request().method() === "POST"
      ),
      launch.createButton.click(),
    ]);
    expect(response.status()).toBe(400);
    await expect(launch.toast(/HTTP 400/)).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`/models/launch/${model.id}$`));
  });

  test("the error toast carries the backend detail", async ({ page, api }) => {
    const model = await firstLlm(api);
    const launch = new LaunchModelPage(page);
    await openLaunch(page, launch, model.id);
    await launch.skipButton.click();
    await launch.selectEngine("vLLM");
    await launch.nextButton.click();
    await launch.createButton.click();
    await expect(launch.toast("HuggingFace API token not set")).toBeVisible();
  });
});

test.describe("serving options", () => {
  test("an Ollama tag offers only its Ollama option and needs no host", async ({
    page,
    api,
  }) => {
    const models = await api.models();
    // qwen3:0.6b is the seeded Ollama-only catalog entry (also used by
    // e2e/cluster/chat-lifecycle.spec.ts): its only serving option is
    // ("Ollama", "qwen3:0.6b").
    const ollamaModel = models.find((m) => m.modelId === "qwen3:0.6b");
    expect(
      ollamaModel,
      "the catalog should contain the qwen3:0.6b Ollama tag"
    ).toBeTruthy();

    const launch = new LaunchModelPage(page);
    await openLaunch(page, launch, ollamaModel!.id);

    // The accelerator step is optional: the tabs are enabled and Next
    // moves on without a host, because the Ollama serving option's engine
    // has cpu: true.
    await expect(launch.tab("Deploy Config")).toBeEnabled();
    await expect(launch.cpuHint).toBeVisible();
    await launch.nextButton.click();
    await expect(launch.tab("Deploy Config")).toHaveAttribute(
      "aria-selected",
      "true"
    );

    await launch.engineSelect.click();
    await expect(launch.engineOptions()).toHaveText(["Ollama"]);
    await page.keyboard.press("Escape");
  });

  test("a Hugging Face id offers HuggingFace, vLLM and NIM", async ({
    page,
    api,
  }) => {
    const model = await firstLlm(api);
    const options = await api.servingOptions(model.id);
    const expected = options.filter((o) => o.engine_id).map((o) => o.engine);
    expect(expected).not.toContain("Ollama");
    expect(expected).toEqual(
      expect.arrayContaining(["HuggingFace", "vLLM", "NIM"])
    );

    const launch = new LaunchModelPage(page);
    await openLaunch(page, launch, model.id);
    await launch.skipButton.click();
    await launch.engineSelect.click();
    await expect(launch.engineOptions()).toHaveText(expected);
    await page.keyboard.press("Escape");
  });

  test("resource fields default to one replica and are sent with the launch", async ({
    page,
    api,
  }) => {
    const model = await firstLlm(api);
    const launch = new LaunchModelPage(page);
    await openLaunch(page, launch, model.id);
    await launch.skipButton.click();
    await launch.selectEngine("vLLM");
    await expect(launch.gpuCountSelect).toBeVisible();
    await expect(launch.replicasInput).toHaveValue("1");
    await expect(launch.cpuInput).toHaveValue("");
    await launch.selectGpuCount("2");
    await launch.replicasInput.fill("2");
    await launch.cpuInput.fill("4");
    await launch.memoryInput.fill("16Gi");
    await launch.nextButton.click();

    const [request] = await Promise.all([
      page.waitForRequest(
        (req) =>
          req.url().includes("/inferenceInstance") && req.method() === "POST"
      ),
      launch.createButton.click(),
    ]);
    const body = request.postDataJSON();
    expect(body.gpu_count).toBe(2);
    expect(body.replicas).toBe(2);
    expect(body.cpu).toBe("4");
    expect(body.memory).toBe("16Gi");
    // No Hugging Face token on the TEST_MODE backend: the launch is refused.
    await expect(launch.toast(/HTTP 400/)).toBeVisible();
  });

  test("an Ollama tag hides the GPU count and sends 1", async ({
    page,
    api,
  }) => {
    const models = await api.models();
    const ollamaModel = models.find((m) => m.modelId === "qwen3:0.6b")!;
    // Ollama needs no Hugging Face token, so the TEST_MODE backend would
    // persist a Failed row (the controller cannot load a kubeconfig) that
    // outlives this test; answer the POST here instead and assert the body.
    await page.route("**/api/v1alpha1/inferenceInstance", (route) =>
      route.request().method() === "POST"
        ? route.fulfill({ status: 400, json: { detail: "stubbed" } })
        : route.fallback()
    );
    const launch = new LaunchModelPage(page);
    await openLaunch(page, launch, ollamaModel.id);
    await launch.nextButton.click();
    await launch.selectEngine("Ollama");
    await expect(launch.replicasInput).toBeVisible();
    await expect(launch.gpuCountSelect).toHaveCount(0);
    await launch.nextButton.click();
    const [request] = await Promise.all([
      page.waitForRequest(
        (req) =>
          req.url().includes("/inferenceInstance") && req.method() === "POST"
      ),
      launch.createButton.click(),
    ]);
    const body = request.postDataJSON();
    expect(body.gpu_count).toBe(1);
    expect(body.replicas).toBe(1);
    expect(body).not.toHaveProperty("cpu");
    await expect(launch.toast(/HTTP 400: stubbed/)).toBeVisible();
  });

  test("replicas outside 1 to 16 block the submit", async ({ page, api }) => {
    const model = await firstLlm(api);
    const launch = new LaunchModelPage(page);
    await openLaunch(page, launch, model.id);
    await launch.skipButton.click();
    await launch.selectEngine("vLLM");
    await launch.replicasInput.fill("17");
    await launch.nextButton.click();
    const posts: string[] = [];
    page.on("request", (req) => {
      if (req.method() === "POST") posts.push(req.url());
    });
    await launch.createButton.click();
    await expect(launch.toast("Replicas must be")).toBeVisible();
    expect(posts).toEqual([]);
  });

  test("an invalid memory quantity blocks the submit", async ({
    page,
    api,
  }) => {
    const model = await firstLlm(api);
    const launch = new LaunchModelPage(page);
    await openLaunch(page, launch, model.id);
    await launch.skipButton.click();
    await launch.selectEngine("vLLM");
    await launch.memoryInput.fill("16GB");
    await launch.nextButton.click();
    // The submit must be blocked client-side: a POST here would mean the
    // invalid quantity reached the backend.
    let posted = false;
    await page.route("**/api/v1alpha1/inferenceInstance", (route) => {
      if (route.request().method() === "POST") posted = true;
      return route.fallback();
    });
    await launch.createButton.click();
    await expect(
      launch.toast("Memory must be a Kubernetes quantity")
    ).toBeVisible();
    expect(posted).toBe(false);
  });
});
