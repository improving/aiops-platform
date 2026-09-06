import { test, expect, shortId, FAILED_RESOURCE } from "../fixtures";
import { RegistryPage } from "../pages/registry";
import { ModelCatalogPage } from "../pages/model-catalog";
import { LaunchModelPage } from "../pages/launch-model";

// The TEST_MODE backend runs with AIOPS_CHAT_MOCK=true (playwright.config.ts):
// registry search/fetch read backend/test_fixtures/ instead of the network,
// one canned entry per source regardless of the query
// (backend/api/registry.py _mock_entries): Hugging Face's is
// Qwen/Qwen3-0.6B-GGUF (whose Ollama option is hf.co/...:Q8_0, the quant the
// fixture's siblings carry), Ollama's is qwen3 0.6b (reference qwen3:0.6b).

const HF_FIXTURE_NAME = "Qwen/Qwen3-0.6B-GGUF";
const HF_OLLAMA_OPTION = `Ollama: hf.co/${HF_FIXTURE_NAME}:Q8_0`;

test.describe("registry page", () => {
  test.describe("import, publish and launch", () => {
    // The launch wizard asks for hosts, which the TEST_MODE backend cannot
    // list (GET /hosts answers 500).
    test.use({ allowedConsoleErrors: [FAILED_RESOURCE] });

    test("import from Hugging Face, publish, launch on Ollama, deprecate, delete", async ({
      page,
      api,
    }) => {
      const registry = new RegistryPage(page);
      const catalog = new ModelCatalogPage(page);

      await registry.open();
      await registry.importFromHuggingFace();
      await expect(registry.entryRow(HF_FIXTURE_NAME)).toBeVisible();
      await expect(registry.entryRow(HF_FIXTURE_NAME)).toContainText(
        HF_OLLAMA_OPTION
      );

      // A draft is not on the members' catalog yet.
      await catalog.open();
      await expect(catalog.card(HF_FIXTURE_NAME)).toHaveCount(0);

      // Publish it: Publish flips to Deprecate, and it appears in the catalog.
      await registry.open();
      await registry.publishButton(HF_FIXTURE_NAME).click();
      await expect(registry.deprecateButton(HF_FIXTURE_NAME)).toBeVisible();

      await catalog.open();
      await expect(catalog.card(HF_FIXTURE_NAME)).toBeVisible();

      const entries = await api.registryEntries();
      const entry = entries.find((e) => e.modelId === HF_FIXTURE_NAME);
      expect(entry, "the imported entry should be published").toBeTruthy();

      try {
        // The launch wizard offers only the Ollama serving option (a GGUF
        // repo has no HuggingFace/vLLM/NIM option, only the Ollama pull).
        const launch = new LaunchModelPage(page);
        await launch.open(entry!.id);
        await launch.skipButton.click();
        await launch.engineSelect.click();
        await expect(launch.engineOptions()).toHaveText(["Ollama"]);
        await page.keyboard.press("Escape");

        await registry.open();
        await registry.deprecateButton(HF_FIXTURE_NAME).click();
        await expect(registry.publishButton(HF_FIXTURE_NAME)).toBeVisible();

        await registry.deleteEntry(HF_FIXTURE_NAME);
        await expect(registry.entryRow(HF_FIXTURE_NAME)).toHaveCount(0);
      } finally {
        await api.deleteRegistryEntry(entry!.id);
      }
    });
  });

  test("add manually with two serving options", async ({ page, api }) => {
    const registry = new RegistryPage(page);
    await registry.open();

    const name = `Manual Model ${shortId()}`;
    await registry.addManually({
      name,
      modelId: `org/manual-${shortId()}`,
      category: "llm",
      servingOptions: [
        { engine: "HuggingFace", reference: "org/manual-model" },
        { engine: "vLLM", reference: "org/manual-model" },
      ],
    });

    await expect(registry.entryRow(name)).toBeVisible();
    await expect(registry.entryRow(name)).toContainText(
      "HuggingFace: org/manual-model"
    );
    await expect(registry.entryRow(name)).toContainText(
      "vLLM: org/manual-model"
    );

    const entries = await api.registryEntries();
    const entry = entries.find((e) => e.name === name);
    try {
      await registry.deleteEntry(name);
      await expect(registry.entryRow(name)).toHaveCount(0);
    } finally {
      if (entry) await api.deleteRegistryEntry(entry.id);
    }
  });

  test("cancelling an edit discards the change on the next reopen", async ({
    page,
    api,
  }) => {
    const registry = new RegistryPage(page);
    await registry.open();

    const name = `Manual Model ${shortId()}`;
    await registry.addManually({
      name,
      modelId: `org/manual-${shortId()}`,
      category: "llm",
      servingOptions: [
        { engine: "HuggingFace", reference: "org/manual-model" },
      ],
    });
    await expect(registry.entryRow(name)).toBeVisible();

    const entries = await api.registryEntries();
    const entry = entries.find((e) => e.name === name);
    try {
      // Open, change the name, Cancel: the row (and the backend entry)
      // keep the original name.
      await registry.openEdit(name);
      await expect(registry.editNameInput()).toHaveValue(name);
      await registry.editNameInput().fill(`${name} edited`);
      await registry.cancelEdit();
      await expect(registry.entryRow(name)).toBeVisible();

      // Reopening the same row must show the original name, not the
      // abandoned edit (EditEntryDialog.tsx must reset its prefilled
      // fields even on an X -> null -> X model transition).
      await registry.openEdit(name);
      await expect(registry.editNameInput()).toHaveValue(name);
      await registry.cancelEdit();
    } finally {
      if (entry) await api.deleteRegistryEntry(entry.id);
    }
  });

  test("add an Ollama model from the manifest fixture", async ({
    page,
    api,
  }) => {
    const registry = new RegistryPage(page);
    await registry.open();
    await registry.addOllamaModel();

    const row = registry.entryRow("qwen3 0.6b");
    await expect(row).toBeVisible();
    await expect(row).toContainText("Ollama: qwen3:0.6b");

    const entries = await api.registryEntries();
    const entry = entries.find(
      (e) => e.source === "ollama" && e.source_id === "qwen3:0.6b"
    );
    try {
      await registry.deleteEntry("qwen3 0.6b");
    } finally {
      if (entry) await api.deleteRegistryEntry(entry.id);
    }
  });
});
