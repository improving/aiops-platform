import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class FineTuneFormPage extends AppShell {
  readonly name: Locator;
  readonly datasetPath: Locator;
  readonly textColumn: Locator;
  readonly startButton: Locator;
  readonly importConfigButton: Locator;

  constructor(page: Page) {
    super(page);
    this.name = page.getByLabel("Name of fine-tune job");
    this.datasetPath = page.getByLabel("Dataset Path");
    this.textColumn = page.getByLabel("Text Column", { exact: true });
    this.startButton = page.getByRole("button", { name: "Start" });
    this.importConfigButton = page.getByRole("button", {
      name: "Import Config",
    });
  }

  async open(modelId: string) {
    await this.goto(`/models/${modelId}/finetune`);
  }

  /** Fill the fields that have no default value. */
  async fillMinimal(name: string) {
    await this.name.fill(name);
    await this.datasetPath.fill("e2e/dataset");
    await this.textColumn.fill("text");
  }
}
