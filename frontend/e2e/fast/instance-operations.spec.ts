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
    settingsRead: ["args", "env_vars"],
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

  test("a pending instance says what it waits for, and the line goes once it is ready", async ({
    page,
    api,
  }) => {
    // The one GPU is taken: "Pending" alone would give no reason.
    let current = await mockInstance(api, {
      status: "Pending",
      last_error: null,
      last_error_at: null,
      launch: {
        phase: "Scheduling",
        message:
          "Unschedulable: 0/1 nodes are available: 1 Insufficient nvidia.com/gpu.",
        since: "2026-09-18T11:39:42+00:00",
        // The backend's call, not the wording of `message`: amber.
        needs_attention: true,
        restart_count: 0,
        replicas_total: 1,
      },
    });
    await page.route("**/api/v1alpha1/inferenceInstance", (route) =>
      route.fulfill({ json: [current] })
    );
    await stubDetail(page, () => current);

    const shell = new AppShell(page);
    await shell.goto("/models/endpoints");
    await shell.waitForLoaded();
    const card = page
      .locator('main [data-slot="card"]')
      .filter({ hasText: `ID: ${ID}` });
    await expect(card.locator('[data-slot="launch-progress"]')).toContainText(
      "Scheduling"
    );
    await expect(card.locator('[data-slot="launch-progress"]')).toContainText(
      "Insufficient nvidia.com/gpu"
    );

    const details = new InferenceEndpointPage(page);
    await details.open(ID);
    await details.waitForLoaded();
    // The badge keeps its word; the detail is in a row of its own.
    await expect(details.statusField()).toHaveText("Pending");
    const progress = page.locator('main [data-slot="launch-progress"]');
    await expect(progress).toContainText("Scheduling for");
    await expect(progress).toContainText("Insufficient nvidia.com/gpu");
    await expect(progress).toHaveClass(/amber/);

    // The page polls a pending instance; the next read says it is ready.
    current = { ...current, ready: true, status: "Running", launch: null };
    await expect(details.statusField()).toHaveText("Ready", {
      timeout: 15_000,
    });
    await expect(progress).toHaveCount(0);
  });

  test("a card says what runs, its name for Chat, and offers the action its state calls for", async ({
    page,
    api,
  }) => {
    const base = await mockInstance(api, {
      last_error: null,
      last_error_at: null,
    });
    const serving = {
      ...base,
      ready: true,
      status: "Running",
      model: {
        ...(base.model as object),
        parameters: 7615616512,
        size: 5.2 * 1024 ** 3,
      },
    };
    const starting = {
      ...base,
      id: "11111111-2222-4333-8444-5555beefbeef",
      ready: false,
      status: "Pending",
    };
    // Ready, but nothing the Chat page lists: it has no chat capability.
    const embedding = {
      ...serving,
      id: "22222222-3333-4444-8555-6666feedfeed",
      model: { ...serving.model, category: "embedding" },
    };
    await page.route("**/api/v1alpha1/inferenceInstance", (route) =>
      route.fulfill({ json: [serving, starting, embedding] })
    );

    const shell = new AppShell(page);
    await shell.goto("/models/endpoints");
    await shell.waitForLoaded();
    const cards = page.locator('main [data-slot="card"]');

    const ready = cards.filter({ hasText: `ID: ${ID}` });
    await expect(ready.locator('[data-slot="accelerator"]')).toHaveText(
      "1 GPU"
    );
    const facts = ready.locator('[data-slot="instance-facts"]');
    await expect(facts).toContainText("7.6B parameters");
    await expect(facts).toContainText("5.2 GB weights");
    // The name Chat, Langflow and the API know the instance by.
    await expect(facts).toContainText("inst-0000cafe");
    await expect(ready.getByRole("link", { name: "Chat" })).toHaveAttribute(
      "href",
      "/chat?target=inst-0000cafe"
    );
    await expect(ready.getByRole("link", { name: "Logs" })).toHaveCount(0);

    // Not ready: the log is what helps, and there is nothing to chat with.
    const pending = cards.filter({ hasText: "5555beefbeef" });
    await expect(pending.getByRole("link", { name: "Logs" })).toHaveAttribute(
      "href",
      `/models/endpoints/${starting.id}?tab=logs`
    );
    await expect(pending.getByRole("link", { name: "Chat" })).toHaveCount(0);

    // Cards of one row start their content at one height, whatever they
    // carry below it: a footer action, a banner, a progress line or none.
    const stopped = {
      ...base,
      id: "33333333-4444-4555-8666-7777deaddead",
      ready: false,
      status: "Stopped",
    };
    await page.route("**/api/v1alpha1/inferenceInstance", (route) =>
      route.fulfill({ json: [serving, stopped] })
    );
    await page.getByRole("button", { name: "Refresh" }).click();
    const stoppedCard = cards.filter({ hasText: "7777deaddead" });
    await expect(stoppedCard).toContainText("Stopped");
    await expect(stoppedCard.getByRole("link")).toHaveCount(1); // the title
    const top = async (card: typeof ready) =>
      (await card.locator('[data-slot="accelerator"]').boundingBox())!.y;
    expect(
      Math.abs((await top(ready)) - (await top(stoppedCard)))
    ).toBeLessThan(2);

    await page.route("**/api/v1alpha1/inferenceInstance", (route) =>
      route.fulfill({ json: [serving, starting, embedding] })
    );
    await page.getByRole("button", { name: "Refresh" }).click();
    const embedder = cards.filter({ hasText: "6666feedfeed" });
    await expect(embedder.locator('[data-slot="accelerator"]')).toBeVisible();
    await expect(embedder.getByRole("link", { name: "Chat" })).toHaveCount(0);
  });

  test("a starting instance shows how far its model download is", async ({
    page,
    api,
  }) => {
    const GB = 1e9;
    const starting = (done: number, message: string) => ({
      phase: "Starting",
      message,
      since: "2026-09-18T14:41:59+00:00",
      needs_attention: false,
      restart_count: 0,
      replicas_total: 1,
      downloaded_bytes: done,
      total_bytes: 10 * GB,
    });
    let current = await mockInstance(api, {
      status: "Pending",
      last_error: null,
      last_error_at: null,
      launch: starting(8 * GB, "Downloading the model: 8.0 of 10.0 GB"),
    });
    await page.route("**/api/v1alpha1/inferenceInstance", (route) =>
      route.fulfill({ json: [current] })
    );
    await stubDetail(page, () => current);

    const details = new InferenceEndpointPage(page);
    await details.open(ID);
    await details.waitForLoaded();
    await expect(details.statusField()).toHaveText("Pending");
    const progress = page.locator('main [data-slot="launch-progress"]');
    await expect(progress).toContainText("Downloading the model");
    const bar = progress.getByRole("progressbar", { name: "Model download" });
    await expect(bar).toHaveAttribute("aria-valuenow", "80");
    await expect(progress).toContainText("8.0 of 10.0 GB (80 %)");
    // One amount says nothing about a speed.
    await expect(progress).not.toContainText("MB/s");

    // The page polls a pending instance: a later amount gives a speed and
    // the time left.
    await page.waitForTimeout(11_000);
    current = {
      ...current,
      launch: starting(9 * GB, "Downloading the model: 9.0 of 10.0 GB"),
    };
    await expect(bar).toHaveAttribute("aria-valuenow", "90", {
      timeout: 15_000,
    });
    await expect(progress).toContainText(/MB\/s, about .* left/, {
      timeout: 15_000,
    });

    // Complete: the model loads, and there is no bar any more.
    current = {
      ...current,
      launch: starting(
        10 * GB,
        "The model is downloaded: loading it into GPU memory and compiling"
      ),
    };
    await expect(progress).toContainText("loading it into GPU memory", {
      timeout: 15_000,
    });
    await expect(bar).toHaveCount(0);
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

  test("the Events tab limits a long list, scrolls it and filters the warnings", async ({
    page,
    api,
  }) => {
    // A restart loop writes dozens of events; the list must not grow the page.
    const running = await mockInstance(api, {
      ready: true,
      status: "Running",
      last_error: null,
      last_error_at: null,
    });
    await stubDetail(page, () => running);
    const events = Array.from({ length: 60 }, (_, i) => ({
      at: `2026-09-06T10:${String(59 - i).padStart(2, "0")}:00`,
      type: i % 10 === 0 ? "Warning" : "Normal",
      reason: i % 10 === 0 ? "Unhealthy" : "Pulled",
      message: `event number ${i}`,
      object: "Pod/vllm-0000cafe-abc",
      // Kubernetes folds repeats into one event: the newest one here is a
      // readiness probe that failed 111 times while the model loaded.
      count: i === 0 ? 111 : 1,
      first_at: i === 0 ? "2026-09-06T10:30:00" : null,
    }));
    await page.route(
      `**/api/v1alpha1/inferenceInstance/${ID}/events`,
      (route) => route.fulfill({ json: events })
    );

    const details = new InferenceEndpointPage(page);
    await details.open(ID);
    await details.waitForLoaded();
    await details.tab("Events").click();

    const rows = details.eventsTable.locator("tbody tr");
    await expect(rows).toHaveCount(25);
    await expect(rows.first()).toContainText("×111");
    await expect(rows.nth(1)).not.toContainText("×");
    const count = page.locator('main [data-slot="events-count"]');
    await expect(count).toHaveText("25 of 60, newest first");
    // The list scrolls inside its own area instead of growing the page.
    const scrolls = await details.eventsTable
      .locator("xpath=..")
      .evaluate((el) => el.scrollHeight > el.clientHeight);
    expect(scrolls).toBe(true);

    await page.getByRole("combobox", { name: "Events shown" }).click();
    await page.getByRole("option", { name: "100" }).click();
    await expect(rows).toHaveCount(60);

    await page.getByRole("switch", { name: "Warnings only" }).click();
    await expect(rows).toHaveCount(6);
    await expect(count).toHaveText("6 of 6, newest first");
    await expect(details.eventsTable).toContainText("Unhealthy");
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

  test("Edit settings shows the instance's values, adds tool calling, and sends only its own", async ({
    page,
    api,
  }) => {
    let state = await mockInstance(api, {
      status: "Running",
      ready: true,
      last_error: null,
      last_error_at: null,
      reference: "Qwen/Qwen2.5-Coder-14B-Instruct-AWQ",
      config: {
        id: "c",
        lora_adapters: [],
        env_vars: {},
        args: { max_model_len: "4192", "--dtype": "half" },
        enable_tracing: false,
      },
    });
    await stubDetail(page, () => state);
    const bodies: Record<string, Record<string, string>>[] = [];
    await page.route(
      `**/api/v1alpha1/inferenceInstance/${ID}/settings`,
      (route) => {
        const body = route.request().postDataJSON();
        bodies.push(body);
        state = {
          ...state,
          status: "Pending",
          ready: false,
          config: { ...(state.config as object), ...body },
        };
        return route.fulfill({ json: state });
      }
    );

    const details = new InferenceEndpointPage(page);
    await details.open(ID);
    await details.waitForLoaded();
    const dialog = await details.openEditSettings();
    await expect(dialog).toContainText("Saving restarts the instance");

    // The engine default carries the instance's own value; its own extra
    // argument is a row too.
    const argNames = dialog.getByPlaceholder("Argument Name");
    const names = () =>
      argNames.evaluateAll((els) =>
        els.map((el) => (el as HTMLInputElement).value)
      );
    expect(await names()).toEqual(["max_model_len", "port", "--dtype"]);
    const args = dialog.getByRole("region", { name: "CLI arguments" });
    await expect(args.getByPlaceholder("Value").first()).toHaveValue("4192");

    await args.getByPlaceholder("Value").first().fill("16384");
    await dialog.getByRole("switch", { name: "Tool calling" }).click();
    expect(await names()).toEqual([
      "max_model_len",
      "port",
      "--dtype",
      "--enable-auto-tool-choice",
      "--tool-call-parser",
    ]);
    // Qwen's parser, from the instance's model reference.
    await expect(args.getByPlaceholder("Value").last()).toHaveValue("hermes");

    await dialog.getByRole("button", { name: "Save and restart" }).click();
    await expect(details.toast("Settings saved")).toBeVisible();
    await expect(dialog).toBeHidden();
    await expect(details.statusField()).toHaveText("Pending");

    // Own values only: the untouched `port` default is not sent.
    expect(bodies).toEqual([
      {
        args: {
          max_model_len: "16384",
          "--dtype": "half",
          "--enable-auto-tool-choice": "",
          "--tool-call-parser": "hermes",
        },
        env_vars: {},
      },
    ]);

    // A name used twice would lose a row in the request: say so first.
    const dup = await details.openEditSettings();
    await dup.getByRole("button", { name: "Add Argument" }).click();
    await dup.getByPlaceholder("Argument Name").last().fill("port");
    await expect(dup.getByRole("alert")).toContainText("port is there twice");
    await expect(
      dup.getByRole("button", { name: "Save and restart" })
    ).toBeDisabled();
    await dup.getByRole("button", { name: "Cancel" }).click();
    await expect(dup).toBeHidden();

    // Off again removes both rows.
    const again = await details.openEditSettings();
    const toggle = again.getByRole("switch", { name: "Tool calling" });
    await expect(toggle).toBeChecked();
    await toggle.click();
    await expect(again.getByPlaceholder("Argument Name")).toHaveCount(3);
  });

  test("Edit settings is not offered where the engine reads no settings", async ({
    page,
    api,
  }) => {
    const nim = (await api.engines()).find((e) => e.name === "NIM")!;
    const state = await mockInstance(api, {
      status: "Running",
      ready: true,
      last_error: null,
      engine: nim,
      settingsRead: [],
    });
    await stubDetail(page, () => state);
    const details = new InferenceEndpointPage(page);
    await details.open(ID);
    await details.waitForLoaded();
    await details.actionsButton.click();
    await expect(page.getByRole("menuitem", { name: "Restart" })).toBeVisible();
    await expect(
      page.getByRole("menuitem", { name: "Edit settings…" })
    ).toHaveCount(0);
  });

  test("Access splits API and Langflow, each with its own values", async ({
    page,
    api,
  }) => {
    // #36: two audiences were interleaved in one block, repeating the
    // base URL and model four times. Each tab now answers one question:
    // a caller outside the cluster needs the gateway host and the key, a
    // flow in Langflow needs only the name Langflow lists, since the
    // Develop page has put the organization's LiteLLM into Langflow.
    const ready = await mockInstance(api, {
      status: "Running",
      ready: true,
      litellm_model_name: "inst-0000cafe",
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

    // The name to pick, the provider slot it sits under, and nothing to
    // paste: no Service address, no key, no code examples.
    const lfFields = main.getByRole("group", { name: "Langflow fields" });
    await expect(lfFields).toContainText("inst-0000cafe");
    await expect(lfFields).toContainText("OpenAI Compatible");
    await expect(lfFields).not.toContainText("ai-stack.svc");
    // Field passes its label through to CopyButton unchanged, so the
    // accessible name is "Copy Model name"; match case-insensitively.
    await expect(
      lfFields.getByRole("button", { name: /copy model name/i })
    ).toBeVisible();
    await expect(
      main.getByRole("group", { name: "curl example" })
    ).toBeHidden();
    await expect(
      main.getByRole("link", { name: "Open Langflow" })
    ).toHaveAttribute("href", "/develop");
  });
});
