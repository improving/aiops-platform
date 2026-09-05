import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

/** One provider kind's label in the "Add provider" dialog's Kind select. */
export const PROVIDER_KIND_LABELS: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Google Gemini",
  groq: "Groq",
  openrouter: "OpenRouter",
};

export class ProvidersPage extends AppShell {
  readonly addProviderButton: Locator;
  readonly budgetInput: Locator;
  readonly saveBudgetButton: Locator;

  constructor(page: Page) {
    super(page);
    this.addProviderButton = page.getByRole("button", {
      name: "Add provider",
    });
    this.budgetInput = page.getByRole("textbox", {
      name: "Monthly budget (USD)",
    });
    this.saveBudgetButton = page.getByRole("button", { name: "Save budget" });
  }

  async open() {
    await this.goto("/providers");
  }

  /** The provider's row in the table (identified by its exact name). */
  providerRow(name: string): Locator {
    return this.page.getByRole("row", { name, exact: true });
  }

  expandButton(name: string): Locator {
    return this.page.getByRole("button", { name: `${name} models` });
  }

  enabledSwitch(name: string): Locator {
    return this.providerRow(name).getByRole("switch", { name: "Enabled" });
  }

  discoverModelsButton(name: string): Locator {
    return this.providerRow(name).getByRole("button", {
      name: "Discover models",
    });
  }

  deleteProviderButton(name: string): Locator {
    return this.providerRow(name).getByRole("button", {
      name: "Delete provider",
    });
  }

  removeModelButton(providerName: string, modelId: string): Locator {
    return this.page.getByRole("button", {
      name: `Remove ${modelId} from ${providerName}`,
    });
  }

  modelCell(modelId: string): Locator {
    return this.page.getByRole("cell", { name: modelId, exact: true });
  }

  /** Delete a provider through the table's confirm dialog. */
  async deleteProvider(name: string) {
    await this.deleteProviderButton(name).click();
    await this.confirmDelete();
  }

  /**
   * Fill and submit the "Add provider" dialog: pick `kind` (a value from
   * `PROVIDER_KIND_LABELS`), discover models, then check every id in
   * `models` before saving.
   */
  async addProvider(options: {
    kind: string;
    name: string;
    apiKey: string;
    baseUrl?: string;
    models: string[];
  }) {
    await this.addProviderButton.click();
    const dialog = this.page.getByRole("dialog", { name: "Add provider" });

    await dialog.getByRole("combobox", { name: "Kind" }).click();
    await this.page
      .getByRole("option", { name: PROVIDER_KIND_LABELS[options.kind] })
      .click();
    await dialog.getByRole("textbox", { name: "Name" }).fill(options.name);
    if (options.baseUrl) {
      await dialog
        .getByRole("textbox", { name: "Base URL (optional)" })
        .fill(options.baseUrl);
    }
    await dialog.getByRole("textbox", { name: "API key" }).fill(options.apiKey);

    await dialog.getByRole("button", { name: "Discover models" }).click();
    // Every discovered model starts checked; check exactly the requested
    // ids by walking the checkbox ids ("provider-model-<model id>") rather
    // than assuming which models discovery returned.
    const checkboxes = dialog.locator('[id^="provider-model-"]');
    const count = await checkboxes.count();
    for (let i = 0; i < count; i += 1) {
      const checkbox = checkboxes.nth(i);
      const id = (await checkbox.getAttribute("id"))!.replace(
        "provider-model-",
        ""
      );
      const shouldCheck = options.models.includes(id);
      if ((await checkbox.isChecked()) !== shouldCheck) {
        if (shouldCheck) await checkbox.check();
        else await checkbox.uncheck();
      }
    }

    await dialog.getByRole("button", { name: "Save provider" }).click();
    await dialog.waitFor({ state: "hidden" });
  }
}
