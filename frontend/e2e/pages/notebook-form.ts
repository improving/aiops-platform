import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export class NotebookFormPage extends AppShell {
  readonly name: Locator;
  readonly type: Locator;
  readonly framework: Locator;
  readonly cpu: Locator;
  readonly memory: Locator;
  readonly gpuSwitch: Locator;
  readonly gpuCount: Locator;
  readonly storage: Locator;
  readonly launchButton: Locator;

  constructor(page: Page) {
    super(page);
    this.name = page.getByLabel("Name", { exact: true });
    this.type = page.getByLabel("Type", { exact: true });
    this.framework = page.getByLabel("Framework", { exact: true });
    this.cpu = page.getByLabel("Resources CPU");
    this.memory = page.getByLabel("Resources Memory (GB)");
    this.gpuSwitch = page.getByLabel("Nvidia GPU");
    this.gpuCount = page.getByLabel("Resources GPU");
    this.storage = page.getByLabel("Storage Size (GB)");
    this.launchButton = page.getByRole("button", { name: /Launch/ });
  }

  async open() {
    await this.goto("/notebooks/new");
  }

  async selectType(label: "Jupyter" | "VSCode") {
    await this.type.click();
    await this.page.getByRole("option", { name: label, exact: true }).click();
  }

  /**
   * The helper text (shadcn FormDescription) attached to a field through
   * aria-describedby. Resolves to an empty locator when the field has none.
   */
  async description(field: Locator): Promise<Locator> {
    const ids = (await field.getAttribute("aria-describedby")) ?? "";
    const id = ids
      .split(/\s+/)
      .find((candidate) => candidate.endsWith("-form-item-description"));
    return this.page.locator(id ? `[id="${id}"]` : "#no-such-description");
  }
}
