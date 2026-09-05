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

  test("only LLM-capable engines are offered for an LLM", async ({
    page,
    api,
  }) => {
    const model = await firstLlm(api);
    const engines = await api.engines();
    // Ollama is llm_support too, but it only serves its own registry tags
    // (the "CPU engines" tests below), never a Hugging Face id.
    const llmEngines = engines
      .filter((e) => e.llm_support && e.name !== "Ollama")
      .map((e) => e.name);

    const launch = new LaunchModelPage(page);
    await openLaunch(page, launch, model.id);
    await launch.skipButton.click();
    await launch.engineSelect.click();
    await expect(page.getByRole("option")).toHaveText(llmEngines);
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

test.describe("CPU engines", () => {
  test("an Ollama tag offers only Ollama and needs no host", async ({
    page,
    api,
  }) => {
    const models = await api.models();
    const ollamaModel = models.find(
      (m) => m.modelId.includes(":") && !m.modelId.includes("/")
    );
    expect(
      ollamaModel,
      "the catalog should contain an Ollama tag"
    ).toBeTruthy();

    const launch = new LaunchModelPage(page);
    await openLaunch(page, launch, ollamaModel!.id);

    // The accelerator step is optional: the tabs are enabled and Next
    // moves on without a host.
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

  test("a Hugging Face id does not offer Ollama", async ({ page, api }) => {
    const model = await firstLlm(api);
    const launch = new LaunchModelPage(page);
    await openLaunch(page, launch, model.id);
    await launch.skipButton.click();
    await launch.engineSelect.click();
    const options = await launch.engineOptions().allTextContents();
    await page.keyboard.press("Escape");
    expect(options).not.toContain("Ollama");
    expect(options).toContain("vLLM");
  });
});
