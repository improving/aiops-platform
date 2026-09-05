import {
  test,
  expect,
  helmReleases,
  waitForHelmReleaseGone,
} from "../fixtures";
import { LaunchModelPage } from "../pages/launch-model";
import { InferenceEndpointPage } from "../pages/inference-endpoint";
import { ChatPage } from "../pages/chat";

const CREATE_TIMEOUT = 3 * 60_000;
// First run on a node: the 2.6 GiB Ollama image plus the model pull.
const READY_TIMEOUT = 12 * 60_000;
const ANSWER_TIMEOUT = 3 * 60_000;
const DELETE_TIMEOUT = 2 * 60_000;
const MODEL_TAG = "qwen3:0.6b";

test.describe("chat with a small model on Ollama", { tag: "@cluster" }, () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(25 * 60_000);

  const leftovers: string[] = [];

  test.afterEach(async ({ userApi }) => {
    for (const id of leftovers.splice(0)) {
      await (await userApi("admin")).deleteInferenceInstance(id);
      await waitForHelmReleaseGone(`ollama-${id.slice(0, 8)}`);
    }
  });

  test("launch qwen3 on Ollama, ask a question, delete", async ({
    page,
    api,
  }) => {
    const model = (await api.models()).find((m) => m.modelId === MODEL_TAG);
    expect(model, `catalog has ${MODEL_TAG}`).toBeTruthy();
    const before = new Set((await api.inferenceInstances()).map((i) => i.id));

    const launch = new LaunchModelPage(page);
    await launch.open(model!.id);
    await launch.nextButton.click(); // CPU engine: no host needed
    await launch.selectEngine("Ollama");
    await launch.nextButton.click();
    await launch.createButton.click();
    await expect(
      launch.toast("Inference instance created successfully")
    ).toBeVisible({ timeout: CREATE_TIMEOUT });
    await expect(page).toHaveURL(/\/models\/endpoints\/[0-9a-f-]+$/);

    const created = (await api.inferenceInstances()).filter(
      (i) => !before.has(i.id)
    );
    expect(created, "exactly one new instance").toHaveLength(1);
    const id = created[0].id;
    leftovers.push(id);
    const release = `ollama-${id.slice(0, 8)}`;
    expect(helmReleases()).toContain(release);

    const ready = await api.waitForInferenceReady(id, READY_TIMEOUT);
    expect(ready.endpoint).toMatch(/^https:\/\/inf-/);

    const details = new InferenceEndpointPage(page);
    await details.open(id);
    await details.chatButton.click();
    await expect(page).toHaveURL(new RegExp(`/chat\\?instance=${id}$`));

    const chat = new ChatPage(page);
    await expect(chat.targetSelect).toContainText(model!.name);
    await chat.send("Reply with the single word pong.");
    await expect(chat.assistantMessages.last()).not.toBeEmpty({
      timeout: ANSWER_TIMEOUT,
    });
    await expect(chat.stopButton).toBeHidden({ timeout: ANSWER_TIMEOUT });
    const answer = await chat.assistantMessages.last().innerText();
    expect(answer.trim().length).toBeGreaterThan(0);

    await details.open(id);
    await details.deleteInstance(DELETE_TIMEOUT);
    await expect
      .poll(async () => (await api.inferenceInstances()).map((i) => i.id))
      .not.toContain(id);
    await waitForHelmReleaseGone(release);
    leftovers.length = 0;
  });
});
