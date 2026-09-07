import { execFileSync } from "node:child_process";
import {
  test,
  expect,
  helmReleases,
  waitForHelmReleaseGone,
  HELM_NAMESPACE,
  type BackendApi,
} from "../fixtures";
import { LaunchModelPage } from "../pages/launch-model";
import { InferenceEndpointPage } from "../pages/inference-endpoint";

const MODEL_TAG = "qwen3:0.6b";
const CREATE_TIMEOUT = 3 * 60_000;
// First run on a node: the 2.6 GiB Ollama image plus the model pull.
const READY_TIMEOUT = 12 * 60_000;
const ACTION_TIMEOUT = 3 * 60_000;
const DELETE_TIMEOUT = 2 * 60_000;

/** Pod names of the release, straight from the cluster. */
function podsOf(release: string): string[] {
  const out = execFileSync(
    "kubectl",
    [
      "-n",
      HELM_NAMESPACE,
      "get",
      "pods",
      "-l",
      `app.kubernetes.io/instance=${release}`,
      "-o",
      "jsonpath={.items[*].metadata.name}",
    ],
    { encoding: "utf8" }
  );
  return out.split(/\s+/).filter(Boolean);
}

async function waitForStatus(
  api: BackendApi,
  id: string,
  status: string,
  timeout: number
) {
  await expect
    .poll(async () => (await api.inferenceInstance(id))?.status ?? null, {
      message: `instance ${id} did not reach status ${status}`,
      timeout,
      intervals: [5_000],
    })
    .toBe(status);
}

test.describe("day-2 operations on Ollama", { tag: "@cluster" }, () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(35 * 60_000);

  const leftovers: string[] = [];
  // Snapshotted before the test creates anything, so a failure between the
  // create call and `leftovers.push(id)` below (a POST that succeeds but a
  // timed-out toast, say) still leaves a trail `afterEach` can find and
  // delete: any instance present afterwards and absent here is ours.
  // `before` stays null until the snapshot actually lands, so a beforeEach
  // that throws first (an unreachable API, say) leaves afterEach skipping
  // the diff instead of treating every organization instance as ours.
  let before: Set<string> | null = null;

  test.beforeEach(async ({ api }) => {
    before = new Set((await api.inferenceInstances()).map((i) => i.id));
  });

  test.afterEach(async ({ userApi, api }) => {
    const toDelete = new Set(leftovers.splice(0));
    if (before !== null) {
      const snapshot = before;
      const now = await api.inferenceInstances();
      for (const instance of now) {
        if (!snapshot.has(instance.id)) toDelete.add(instance.id);
      }
    } else {
      console.error(
        "afterEach: no pre-test snapshot (beforeEach did not complete); skipping the leftover-instance diff"
      );
    }
    const admin = await userApi("admin");
    for (const id of toDelete) {
      // One instance's cleanup failing (already gone, a transient 5xx, ...)
      // must not skip the rest.
      try {
        await admin.deleteInferenceInstance(id);
        await waitForHelmReleaseGone(`ollama-${id.slice(0, 8)}`);
      } catch (error) {
        console.error(`afterEach: failed to clean up instance ${id}`, error);
      }
    }
    before = null;
  });

  test("launch, logs, events, restart, stop, resume, delete", async ({
    page,
    api,
  }) => {
    const model = (await api.models()).find((m) => m.modelId === MODEL_TAG);
    expect(model, `catalog has ${MODEL_TAG}`).toBeTruthy();

    // Launch from the wizard; the CPU engine needs no host.
    const launch = new LaunchModelPage(page);
    await launch.open(model!.id);
    await launch.nextButton.click();
    await launch.selectEngine("Ollama");
    await expect(launch.gpuCountSelect).toHaveCount(0);
    await expect(launch.replicasInput).toHaveValue("1");
    // The lab node has ~8 GiB and already runs the developer's own Ollama
    // instance; the default 2Gi request does not fit alongside it, so this
    // spec pins a smaller footprint (also verifying the launch resource
    // fields against a real pod, not just the snapshot in test_controller.py).
    await launch.cpuInput.fill("1");
    await launch.memoryInput.fill("1536Mi");
    await launch.nextButton.click();
    await launch.createButton.click();
    await expect(
      launch.toast("Inference instance created successfully")
    ).toBeVisible({ timeout: CREATE_TIMEOUT });

    // beforeEach must have completed for the test body to run at all, so
    // the pre-test snapshot is set here.
    const created = (await api.inferenceInstances()).filter(
      (i) => !before!.has(i.id)
    );
    expect(created, "exactly one new instance").toHaveLength(1);
    const id = created[0].id;
    leftovers.push(id);
    const release = `ollama-${id.slice(0, 8)}`;
    expect(helmReleases()).toContain(release);
    expect(created[0].status).toBe("Pending");

    // Ready: the poller flips the persisted status to Running.
    await api.waitForInferenceReady(id, READY_TIMEOUT);
    await waitForStatus(api, id, "Running", ACTION_TIMEOUT);
    const details = new InferenceEndpointPage(page);
    await details.open(id);
    await details.waitForLoaded();
    await expect(details.statusField()).toHaveText("Ready");
    await expect(details.errorBanner).toHaveCount(0);

    // Logs: the UI tab and the API agree.
    await details.tab("Logs").click();
    await expect(details.logOutput).not.toHaveText("(empty)", {
      timeout: 60_000,
    });
    const logs = await api.get(`/inferenceInstance/${id}/logs?tail=50`);
    expect(logs.ok(), `logs -> ${logs.status()}`).toBeTruthy();
    const logsBody = (await logs.json()) as {
      pods: { name: string; containers: { name: string; log: string }[] }[];
    };
    expect(logsBody.pods.length).toBeGreaterThan(0);
    // Real Ollama output, not just any non-empty text: its structured log
    // lines carry `level=`/`msg=` (slog), and the startup line says so too.
    expect(logsBody.pods[0].containers[0].log).toMatch(
      /level=|msg=|Listening on/
    );

    // Events: at least the scheduling and image events of the pod.
    await details.tab("Events").click();
    await expect(details.eventsTable).toContainText(/Scheduled|Pulled|Started/);
    const events = await api.get(`/inferenceInstance/${id}/events`);
    expect(events.ok(), `events -> ${events.status()}`).toBeTruthy();
    expect(((await events.json()) as unknown[]).length).toBeGreaterThan(0);

    // Restart: a new pod replaces the old one and the instance is ready again.
    const podsBefore = podsOf(release);
    expect(podsBefore).toHaveLength(1);
    await details.tab("Details").click();
    await details.runAction("Restart", "Restart");
    await expect(details.toast("Restart requested")).toBeVisible();
    await expect
      .poll(() => podsOf(release), {
        message: "the pod was not replaced",
        timeout: ACTION_TIMEOUT,
        intervals: [5_000],
      })
      .not.toEqual(podsBefore);
    await api.waitForInferenceReady(id, READY_TIMEOUT);
    await waitForStatus(api, id, "Running", ACTION_TIMEOUT);

    // Stop: replicas 1 -> 0, the pods are gone, the row says Stopped.
    await details.runAction("Stop", "Stop");
    await expect(details.toast("Instance stopped")).toBeVisible();
    await expect(details.statusField()).toHaveText("Stopped");
    await expect
      .poll(() => podsOf(release), {
        message: "the pods did not go away",
        timeout: ACTION_TIMEOUT,
        intervals: [5_000],
      })
      .toEqual([]);
    const stopped = await api.inferenceInstance(id);
    expect(stopped!.status).toBe("Stopped");
    expect(stopped!.ready).toBe(false);

    // Resume: replicas 0 -> 1, ready again.
    await details.runAction("Resume", "Resume");
    await expect(details.toast("Instance resumed")).toBeVisible();
    await expect(details.statusField()).toHaveText("Pending");
    await api.waitForInferenceReady(id, READY_TIMEOUT);
    await waitForStatus(api, id, "Running", ACTION_TIMEOUT);
    expect(podsOf(release)).toHaveLength(1);
    await page.reload();
    await details.waitForLoaded();
    await expect(details.statusField()).toHaveText("Ready");

    // Delete from the UI; the release goes away.
    await details.deleteInstance(DELETE_TIMEOUT);
    await expect
      .poll(async () => (await api.inferenceInstances()).map((i) => i.id))
      .not.toContain(id);
    await waitForHelmReleaseGone(release);
    leftovers.length = 0;
  });
});
