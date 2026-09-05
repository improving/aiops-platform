import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class RegistryPage extends AppShell {
  readonly importHfButton: Locator;
  readonly addOllamaButton: Locator;
  readonly addHostedButton: Locator;
  readonly addManuallyButton: Locator;
  readonly sourceFilter: Locator;
  readonly capabilityFilter: Locator;
  readonly statusFilter: Locator;

  constructor(page: Page) {
    super(page);
    this.importHfButton = page.getByRole("button", {
      name: "Import from Hugging Face",
    });
    this.addOllamaButton = page.getByRole("button", {
      name: "Add Ollama model",
    });
    this.addHostedButton = page.getByRole("button", {
      name: "Add hosted model",
    });
    this.addManuallyButton = page.getByRole("button", {
      name: "Add manually",
    });
    this.sourceFilter = page.getByRole("combobox", { name: "Source" });
    this.capabilityFilter = page.getByRole("combobox", {
      name: "Capability",
    });
    this.statusFilter = page.getByRole("combobox", { name: "Status" });
  }

  async open() {
    await this.goto("/models/registry");
  }

  /** The entry's row in the table (identified by its exact name). */
  entryRow(name: string): Locator {
    return this.page.getByRole("row", { name, exact: true });
  }

  publishButton(name: string): Locator {
    return this.entryRow(name).getByRole("button", { name: "Publish" });
  }

  deprecateButton(name: string): Locator {
    return this.entryRow(name).getByRole("button", { name: "Deprecate" });
  }

  syncButton(name: string): Locator {
    return this.entryRow(name).getByRole("button", { name: "Sync" });
  }

  editButton(name: string): Locator {
    return this.entryRow(name).getByRole("button", { name: "Edit" });
  }

  deleteEntryButton(name: string): Locator {
    return this.entryRow(name).getByRole("button", { name: "Delete entry" });
  }

  /** Delete an entry through the table's confirm dialog. */
  async deleteEntry(name: string) {
    await this.deleteEntryButton(name).click();
    await this.confirmDelete();
  }

  /**
   * Import the fixture's Hugging Face entry as a draft through the
   * "Import from Hugging Face" dialog. AIOPS_CHAT_MOCK ignores the query
   * and always answers with Qwen/Qwen3-0.6B-GGUF.
   */
  async importFromHuggingFace(query = "qwen") {
    await this.importHfButton.click();
    const dialog = this.page.getByRole("dialog", {
      name: "Import from Hugging Face",
    });
    await dialog
      .getByRole("searchbox", { name: "Search Hugging Face" })
      .fill(query);
    await dialog.getByRole("button", { name: "Search" }).click();
    await dialog.getByRole("button", { name: "Import as draft" }).click();
    // The footer button; the shadcn DialogContent's corner "X" is also
    // named "Close" (see e2e/pages/vector-db-endpoints.ts), so this
    // dialog's own footer button is "Done" instead.
    await dialog.getByRole("button", { name: "Done" }).click();
    await dialog.waitFor({ state: "hidden" });
  }

  /**
   * Import the fixture's Ollama entry as a draft through the "Add Ollama
   * model" dialog. AIOPS_CHAT_MOCK ignores the tag and always answers
   * with qwen3 0.6b.
   */
  async addOllamaModel(tag = "qwen3:0.6b") {
    await this.addOllamaButton.click();
    const dialog = this.page.getByRole("dialog", {
      name: "Add Ollama model",
    });
    await dialog.getByRole("textbox", { name: "Ollama tag" }).fill(tag);
    await dialog.getByRole("button", { name: "Preview" }).click();
    await dialog.getByRole("button", { name: "Import as draft" }).click();
    await dialog.waitFor({ state: "hidden" });
  }

  /** Fill and submit the "Add manually" dialog with one or more serving options. */
  async addManually(options: {
    name: string;
    modelId: string;
    category: string;
    servingOptions: { engine: string; reference: string }[];
  }) {
    await this.addManuallyButton.click();
    const dialog = this.page.getByRole("dialog", { name: "Add manually" });
    await dialog.getByPlaceholder("Model Name").fill(options.name);
    await dialog.getByPlaceholder("Model ID").fill(options.modelId);
    await dialog
      .getByPlaceholder("Category", { exact: true })
      .fill(options.category);

    const rows = dialog.getByTestId("serving-option-row");
    for (let i = 0; i < options.servingOptions.length; i += 1) {
      if (i > 0) {
        await dialog
          .getByRole("button", { name: "Add serving option" })
          .click();
      }
      const row = rows.nth(i);
      await row
        .getByPlaceholder("Engine (e.g. HuggingFace)")
        .fill(options.servingOptions[i].engine);
      await row
        .getByPlaceholder("Reference")
        .fill(options.servingOptions[i].reference);
    }

    await dialog.getByRole("button", { name: "Add", exact: true }).click();
    await dialog.waitFor({ state: "hidden" });
  }
}
