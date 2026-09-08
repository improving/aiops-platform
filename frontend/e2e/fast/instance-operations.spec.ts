import type { Page } from "@playwright/test";
import { test, expect, type BackendApi } from "../fixtures";
import { AppShell } from "../pages/app-shell";
import { InferenceEndpointPage } from "../pages/inference-endpoint";

// The TEST_MODE backend has no cluster, so the instance routes are stubbed
// (the list-controls.spec.ts pattern). The model and engine come from the
// real catalog so the card icon resolves.
const ID = "00000000-0000-0000-0000-00000000cafe";
const LOG = "INFO loading model\nINFO ready";

type Instance = Record<string, unknown> & { status: string | null };

async function mockInstance(
  api: BackendApi,
  overrides: Partial<Instance> = {}
): Promise<Instance> {
  const model = (await api.models()).find((m) => m.category === "llm")!;
  const engine = (await api.engines()).find((e) => e.name === "vLLM")!;
  return {
    id: ID,
    model,
    engine,
    host: "",
    endpoint: "https://inf-0000cafe.example",
    healthEndpoint: "",
    metricsEndpoint: "",
    ready: false,
    status: "Failed",
    last_error: "CrashLoopBackOff: back-off 5m0s restarting failed container",
    last_error_at: "2026-09-06T10:00:00",
    stopped_at: null,
    replicas: 1,
    gpu_count: 1,
    cpu: null,
    memory: null,
    config: {
      id: "c",
      lora_adapters: [],
      env_vars: {},
      args: {},
      enable_tracing: false,
    },
    litellm_model_name: null,
    reference: null,
    ...overrides,
  };
}

/** Stub the detail page's reads; `state()` is read on every GET. */
async function stubDetail(page: Page, state: () => Instance) {
  await page.route(`**/api/v1alpha1/inferenceInstance/${ID}`, (route) =>
    route.fulfill({ json: state() })
  );
  await page.route(
    `**/api/v1alpha1/inferenceInstance/${ID}/dashboards`,
    (route) => route.fulfill({ json: [] })
  );
}

test.describe("instance operations", () => {
  test("a failed instance shows the reason on the card and the detail page", async ({
    page,
    api,
  }) => {
    const failed = await mockInstance(api);
    await page.route("**/api/v1alpha1/inferenceInstance", (route) =>
      route.fulfill({ json: [failed] })
    );
    await stubDetail(page, () => failed);

    const shell = new AppShell(page);
    await shell.goto("/models/endpoints");
    await shell.waitForLoaded();
    const card = page
      .locator('main [data-slot="card"]')
      .filter({ hasText: `ID: ${ID}` });
    await expect(card).toContainText("Failed");
    await expect(card.getByRole("alert")).toContainText("CrashLoopBackOff");
    await expect(card).toContainText("1 replica");

    const details = new InferenceEndpointPage(page);
    await details.open(ID);
    await details.waitForLoaded();
    await expect(details.statusField()).toHaveText("Failed");
    await expect(details.errorBanner).toContainText("back-off 5m0s");
    await expect(
      details.errorBanner.getByRole("button", { name: "Copy error" })
    ).toBeVisible();
  });

  test("the Logs tab renders the mocked log and the Events tab the events", async ({
    page,
    api,
  }) => {
    const running = await mockInstance(api, {
      status: "Running",
      ready: true,
      last_error: null,
      last_error_at: null,
    });
    await stubDetail(page, () => running);
    const tails: string[] = [];
    await page.route(new RegExp(`/inferenceInstance/${ID}/logs`), (route) => {
      tails.push(new URL(route.request().url()).searchParams.get("tail") ?? "");
      return route.fulfill({
        json: {
          pods: [
            {
              name: "vllm-0000cafe-abc",
              containers: [{ name: "vllm", log: LOG }],
            },
          ],
        },
      });
    });
    await page.route(
      `**/api/v1alpha1/inferenceInstance/${ID}/events`,
      (route) =>
        route.fulfill({
          json: [
            {
              at: "2026-09-06T10:00:00",
              type: "Warning",
              reason: "BackOff",
              message: "Back-off restarting failed container",
              object: "Pod/vllm-0000cafe-abc",
            },
          ],
        })
    );

    const details = new InferenceEndpointPage(page);
    await details.open(ID);
    await details.waitForLoaded();
    await details.tab("Logs").click();
    await expect(page).toHaveURL(
      new RegExp(`/models/endpoints/${ID}\\?tab=logs$`)
    );
    await expect(details.logOutput).toContainText("INFO ready");
    await expect(details.containerSelect).toContainText(
      "vllm-0000cafe-abc/vllm"
    );
    expect(tails).toEqual(["200"]);

    await details.linesSelect.click();
    await page.getByRole("option", { name: "1000", exact: true }).click();
    await expect.poll(() => tails).toEqual(["200", "1000"]);
    await expect(
      details.logOutput.locator("..").getByRole("button", { name: "Copy log" })
    ).toBeVisible();

    await details.tab("Events").click();
    await expect(details.eventsTable).toContainText("BackOff");
    await expect(details.eventsTable).toContainText("Pod/vllm-0000cafe-abc");
  });

  test("Stop then Resume flips the badge", async ({ page, api }) => {
    let state = await mockInstance(api, {
      status: "Running",
      ready: true,
      last_error: null,
      last_error_at: null,
      replicas: 2,
    });
    await stubDetail(page, () => state);
    await page.route(
      `**/api/v1alpha1/inferenceInstance/${ID}/stop`,
      (route) => {
        state = {
          ...state,
          status: "Stopped",
          ready: false,
          stopped_at: "2026-09-06T11:00:00",
        };
        return route.fulfill({ json: state });
      }
    );
    await page.route(
      `**/api/v1alpha1/inferenceInstance/${ID}/resume`,
      (route) => {
        state = { ...state, status: "Pending", ready: false, stopped_at: null };
        return route.fulfill({ json: state });
      }
    );

    const details = new InferenceEndpointPage(page);
    await details.open(ID);
    await details.waitForLoaded();
    await expect(details.statusField()).toHaveText("Ready");

    await details.actionsButton.click();
    await expect(page.getByRole("menuitem", { name: "Resume" })).toHaveCount(0);
    await page.keyboard.press("Escape");
    // Radix animates the menu closed (data-[state=closed]:animate-out); wait
    // for it to actually leave the DOM before reopening it, or the trigger
    // click below can race the exit animation and the reopened menu never
    // stabilizes for Playwright's actionability check.
    await expect(page.getByRole("menu")).toHaveCount(0);

    await details.runAction("Stop", "Stop");
    await expect(details.toast("Instance stopped")).toBeVisible();
    await expect(details.statusField()).toHaveText("Stopped");

    await details.actionsButton.click();
    await expect(page.getByRole("menuitem", { name: "Stop" })).toHaveCount(0);
    await expect(
      page.getByRole("menuitem", { name: "Restart" })
    ).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu")).toHaveCount(0);

    await details.runAction("Resume", "Resume");
    await expect(details.toast("Instance resumed")).toBeVisible();
    await expect(details.statusField()).toHaveText("Pending");
  });

  test("Access splits API and Langflow, each with its own values", async ({
    page,
    api,
  }) => {
    // #36: two audiences were interleaved in one block, repeating the
    // base URL and model four times. Each tab now answers one question:
    // a caller outside the cluster needs the gateway host and the key, a
    // flow inside it needs the Service address and no key.
    const ready = await mockInstance(api, {
      status: "Running",
      ready: true,
      clusterEndpoint: "http://ollama-0000cafe.ai-stack.svc:80",
    });
    await stubDetail(page, () => ready);
    await page.route("**/api/v1alpha1/config/ui", (route) =>
      route.fulfill({
        json: {
          grafanaUrl: "",
          langflowUrl: "https://langflow.example.test",
          jaegerUrl: "",
          authMode: "disabled",
        },
      })
    );

    const details = new InferenceEndpointPage(page);
    await details.open(ID);
    await details.waitForLoaded();
    const main = page.locator("main");

    // API access is the default: the gateway host, and the key lives here.
    const apiFields = main.getByRole("group", { name: "API access fields" });
    await expect(apiFields).toContainText("https://inf-0000cafe.example/v1");
    await expect(
      apiFields.getByRole("button", { name: "Show API key" })
    ).toBeVisible();
    // The examples are behind a button, not in the page flow: the fields
    // are what people come back for, the code is read once.
    await expect(main.getByRole("group", { name: "curl example" })).toHaveCount(
      0
    );
    await main.getByRole("button", { name: "Code examples" }).click();
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByRole("group", { name: "curl example" })
    ).toBeVisible();
    await dialog.getByRole("tab", { name: "Python" }).click();
    await expect(
      dialog.getByRole("group", { name: "Python example" })
    ).toBeVisible();
    await expect(
      dialog.getByRole("group", { name: "curl example" })
    ).toBeHidden();
    // Measure curl, not Python: the long single line that pushed the
    // dialog past the viewport is curl's, and Python's longest line fits
    // regardless, so measuring it proves nothing.
    await dialog.getByRole("tab", { name: "curl" }).click();
    const fits = await dialog
      .getByRole("group", { name: "curl example" })
      .evaluate((el) => {
        const d = el.closest('[role="dialog"]') as HTMLElement;
        return (
          el.scrollWidth <= (el as HTMLElement).clientWidth &&
          d.getBoundingClientRect().right <= window.innerWidth
        );
      });
    expect(fits).toBe(true);
    // And the highlighting is actually applied: the CSS variables were
    // self-referencing once, which silently left every token the
    // inherited colour and made the dependency pointless.
    const coloured = await dialog
      .getByRole("group", { name: "curl example" })
      .evaluate((el) => {
        const inherited = getComputedStyle(el).color;
        const tokens = Array.from(
          el.querySelectorAll<HTMLElement>("[class*=sh__token]")
        );
        // A token still wearing the surrounding text colour is one whose
        // variable did not resolve. Counting distinct colours instead
        // would pass while most of them were broken.
        return {
          total: tokens.length,
          unresolved: tokens.filter(
            (t) => getComputedStyle(t).color === inherited
          ).length,
        };
      });
    expect(coloured.total).toBeGreaterThan(5);
    expect(coloured.unresolved).toBe(0);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    // The in-cluster address is not on this tab.
    await expect(main).not.toContainText("ollama-0000cafe.ai-stack.svc");

    await main.getByRole("tab", { name: "Langflow" }).click();

    // The other address, no key, and no code examples to wade through.
    const lfFields = main.getByRole("group", { name: "Langflow fields" });
    await expect(lfFields).toContainText(
      "http://ollama-0000cafe.ai-stack.svc:80/v1"
    );
    await expect(lfFields).toContainText("none needed");
    await expect(
      main.getByRole("group", { name: "curl example" })
    ).toBeHidden();
    await expect(
      main.getByRole("link", { name: "Open Langflow" })
    ).toBeVisible();
  });

  test("the Langflow tab asks for a key only when the engine needs one", async ({
    page,
    api,
  }) => {
    // Skipping the gateway skips its key check, but vLLM reads the key
    // itself, so an in-cluster caller still needs it. Saying "none
    // needed" for every engine sent those users to a 401 with the page
    // telling them the opposite.
    const checks = await mockInstance(api, {
      status: "Running",
      ready: true,
      clusterEndpoint: "http://vllm-0000cafe.ai-stack.svc:80",
      workloadChecksApiKey: true,
    });
    await stubDetail(page, () => checks);

    const details = new InferenceEndpointPage(page);
    await details.open(ID);
    await details.waitForLoaded();
    const main = page.locator("main");
    await main.getByRole("tab", { name: "Langflow" }).click();

    const fields = main.getByRole("group", { name: "Langflow fields" });
    await expect(fields).not.toContainText("none needed");
    await expect(
      fields.getByRole("button", { name: "Show API key" })
    ).toBeVisible();
  });
});
