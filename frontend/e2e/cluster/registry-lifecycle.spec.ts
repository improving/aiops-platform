import {
  test,
  expect,
  helmReleases,
  waitForHelmReleaseGone,
} from "../fixtures";
import { RegistryPage } from "../pages/registry";
import { LaunchModelPage } from "../pages/launch-model";
import { InferenceEndpointPage } from "../pages/inference-endpoint";
import { ChatPage } from "../pages/chat";

const CREATE_TIMEOUT = 3 * 60_000;
// First run on a node: the Ollama image plus the ~400 MB GGUF pull.
const READY_TIMEOUT = 12 * 60_000;
const ANSWER_TIMEOUT = 3 * 60_000;
const DELETE_TIMEOUT = 2 * 60_000;
const SOURCE_ID = "Qwen/Qwen3-0.6B-GGUF";

// Live Hugging Face and Ollama registry, so it never runs in CI: covers the
// full admin lifecycle the fast tier's mocked registry.spec.ts cannot
// (a real GGUF fetch, a real Ollama pull, a real chat answer).
test.describe(
  "import a registry entry from Hugging Face and launch it",
  { tag: "@cluster" },
  () => {
    test.describe.configure({ mode: "serial" });
    test.setTimeout(25 * 60_000);

    const leftoverInstances: string[] = [];
    const leftoverEntries: string[] = [];

    test.afterEach(async ({ userApi }) => {
      const admin = await userApi("admin");
      for (const id of leftoverInstances.splice(0)) {
        await admin.deleteInferenceInstance(id);
        await waitForHelmReleaseGone(`ollama-${id.slice(0, 8)}`);
      }
      for (const id of leftoverEntries.splice(0)) {
        await admin.deleteRegistryEntry(id);
      }
    });

    test("import, publish, launch on Ollama, chat, delete", async ({
      asUser,
      userApi,
    }) => {
      // alice (the default signed-in user) is a member and cannot write to
      // the registry; only an admin can.
      const adminContext = await asUser("admin");
      const page = await adminContext.newPage();
      const admin = await userApi("admin");

      const registry = new RegistryPage(page);
      await registry.open();

      await registry.importHfButton.click();
      const importDialog = page.getByRole("dialog", {
        name: "Import from Hugging Face",
      });
      await importDialog
        .getByRole("searchbox", { name: "Search Hugging Face" })
        .fill(SOURCE_ID);
      await importDialog.getByRole("button", { name: "Search" }).click();
      // One row per search result; the live search also returns other
      // repos that contain the same substring, so match the exact id.
      const result = importDialog
        .getByTestId("hf-result")
        .filter({ has: page.getByText(SOURCE_ID, { exact: true }) });
      await expect(result).toHaveCount(1, { timeout: 60_000 });
      await result.getByRole("button", { name: "Import as draft" }).click();
      await importDialog.getByRole("button", { name: "Done" }).click();

      await expect(registry.entryRow(SOURCE_ID)).toBeVisible();

      const imported = (await admin.registryEntries()).find(
        (e) => e.modelId === SOURCE_ID
      );
      expect(imported, "the entry was created").toBeTruthy();
      leftoverEntries.push(imported!.id);

      const ollamaOption = imported!.serving_options?.find(
        (o) => o.engine === "Ollama"
      );
      expect(ollamaOption, "the GGUF repo has an Ollama option").toBeTruthy();
      expect(ollamaOption!.reference).toMatch(
        new RegExp(`^hf\\.co/${SOURCE_ID.replace("/", "\\/")}:`)
      );

      await registry.publishButton(SOURCE_ID).click();
      await expect(registry.deprecateButton(SOURCE_ID)).toBeVisible();

      const before = new Set(
        (await admin.inferenceInstances()).map((i) => i.id)
      );

      const launch = new LaunchModelPage(page);
      await launch.open(imported!.id);
      await launch.nextButton.click(); // CPU engine: no host needed
      await launch.selectEngine("Ollama");
      await launch.nextButton.click();
      await launch.createButton.click();
      await expect(
        launch.toast("Inference instance created successfully")
      ).toBeVisible({ timeout: CREATE_TIMEOUT });
      await expect(page).toHaveURL(/\/models\/endpoints\/[0-9a-f-]+$/);

      const created = (await admin.inferenceInstances()).filter(
        (i) => !before.has(i.id)
      );
      expect(created, "exactly one new instance").toHaveLength(1);
      const id = created[0].id;
      leftoverInstances.push(id);
      const release = `ollama-${id.slice(0, 8)}`;
      expect(helmReleases()).toContain(release);

      const ready = await admin.waitForInferenceReady(id, READY_TIMEOUT);
      expect(ready.endpoint).toMatch(/^https:\/\/inf-/);

      const target = (await admin.chatTargets()).find(
        (t) => t.instance_id === id
      );
      expect(target, "the instance is a chat target").toBeTruthy();

      const details = new InferenceEndpointPage(page);
      await details.open(id);
      await details.chatButton.click();
      await expect(page).toHaveURL(
        new RegExp(`/chat\\?target=${target!.name}$`)
      );

      const chat = new ChatPage(page);
      await chat.send("Reply with the single word pong.");
      await expect(chat.assistantMessages.last()).not.toBeEmpty({
        timeout: ANSWER_TIMEOUT,
      });
      await expect(chat.stopButton).toBeHidden({ timeout: ANSWER_TIMEOUT });

      await details.open(id);
      await details.deleteInstance(DELETE_TIMEOUT);
      await expect
        .poll(async () => (await admin.inferenceInstances()).map((i) => i.id))
        .not.toContain(id);
      await waitForHelmReleaseGone(release);
      leftoverInstances.length = 0;

      await registry.open();
      await registry.deleteEntry(SOURCE_ID);
      await expect(registry.entryRow(SOURCE_ID)).toHaveCount(0);
      leftoverEntries.length = 0;

      await page.close();
    });
  }
);
