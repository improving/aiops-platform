import { readFileSync } from "node:fs";
import { test, expect, FAILED_RESOURCE, type BackendApi } from "../fixtures";
import { AuditPage } from "../pages/audit";

// The TEST_MODE backend has no cluster (KUBECONFIG points nowhere), so a
// launch fails; the audit middleware still records the POST with its
// outcome, which is what the page lists.

// Any outcome will do: the audit middleware records the POST either way.
// A failed launch keeps its row (status Failed), so the instances the
// launch created are collected and deleted in afterEach: other specs
// assume an empty instance list.
const leftovers: string[] = [];

async function launchOnce(api: BackendApi) {
  const model = (await api.models())[0];
  const engine = (await api.engines()).find((e) => e.name === "Ollama");
  expect(model && engine).toBeTruthy();
  const before = new Set((await api.inferenceInstances()).map((i) => i.id));
  await api.post("/inferenceInstance", {
    model: { id: model.id },
    engine: { id: engine!.id },
    config: {},
  });
  for (const instance of await api.inferenceInstances()) {
    if (!before.has(instance.id)) leftovers.push(instance.id);
  }
}

test.afterEach(async ({ api }) => {
  while (leftovers.length > 0) {
    const id = leftovers.pop()!;
    try {
      await api.deleteInferenceInstance(id);
    } catch (error) {
      console.error(`afterEach: failed to delete instance ${id}`, error);
    }
  }
});

test.describe("audit page", () => {
  test("lists the launch newest first and filters by action", async ({
    page,
    api,
  }) => {
    await launchOnce(api);
    const audit = new AuditPage(page);
    await audit.open();
    await audit.expectHeading("Audit log");
    await audit.waitForLoaded();
    // The middleware commits the event after the response has been sent,
    // so the row may land a moment after launchOnce returns: reload until
    // it is there.
    // Other specs act on instances at the same time, so require the create
    // row of the launch, not any inferenceInstance row.
    const launch = audit
      .rows()
      .filter({ hasText: "inferenceInstance" })
      .filter({ hasText: "create" });
    await expect
      .poll(
        async () => {
          await audit.open();
          await audit.waitForLoaded();
          return launch.count();
        },
        { timeout: 15_000 }
      )
      .toBeGreaterThan(0);
    await expect(launch.first()).toContainText("create");
    await expect(launch.first()).toContainText("dev@example.test");

    await audit.selectAction("delete");
    await audit.applyButton.click();
    await audit.waitForLoaded();
    // A fresh TEST_MODE database has no delete events: the table renders
    // its "No events match." placeholder row, not zero rows. Exclude it
    // so the loop below asserts something instead of passing vacuously,
    // and confirm the create event from above is actually filtered out.
    const rows = audit.rows().filter({ hasNotText: "No events match." });
    const count = await rows.count();
    for (let i = 0; i < count; i += 1) {
      await expect(rows.nth(i)).toContainText("delete");
    }
    await expect(audit.rows().filter({ hasText: "create" })).toHaveCount(0);
  });

  test("Export CSV downloads the audit columns", async ({ page, api }) => {
    await launchOnce(api);
    const audit = new AuditPage(page);
    await audit.open();
    await audit.waitForLoaded();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      audit.exportButton.click(),
    ]);
    expect(download.suggestedFilename()).toBe("audit.csv");
    const text = readFileSync((await download.path())!, "utf8");
    const lines = text.trim().split(/\r?\n/);
    expect(lines[0]).toBe(
      "at,actor,action,resource_kind,resource_id,outcome,request_id"
    );
    expect(lines.length).toBeGreaterThan(1);
  });

  test("a member cannot open the audit log", async ({ asUser }) => {
    const ctx = await asUser("alice");
    const page = await ctx.newPage();
    const audit = new AuditPage(page);
    await audit.open();
    await audit.waitForLoaded();
    await expect(
      page.getByText("Only organization admins can view the audit log.")
    ).toBeVisible();
  });
});

test.describe("audit page without a backend", () => {
  test.use({ allowedConsoleErrors: [FAILED_RESOURCE] });

  test("a failing list shows the error", async ({ page }) => {
    await page.route("**/api/v1alpha1/organizations/current/audit**", (route) =>
      route.fulfill({ status: 503, json: { detail: "Database is away" } })
    );
    const audit = new AuditPage(page);
    await audit.open();
    await expect(audit.toast("Database is away")).toBeVisible();
  });
});
