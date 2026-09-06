import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export type LaunchTab =
  | "Accelerators"
  | "Deploy Config"
  | "CLI Args and Env Variables";

export class LaunchModelPage extends AppShell {
  readonly skipButton: Locator;
  readonly nextButton: Locator;
  readonly engineSelect: Locator;
  readonly tracingSwitch: Locator;
  readonly argNames: Locator;
  readonly envNames: Locator;
  readonly addArgumentButton: Locator;
  readonly addEnvVarButton: Locator;
  readonly createButton: Locator;
  readonly cpuHint: Locator;

  constructor(page: Page) {
    super(page);
    this.skipButton = page.getByRole("button", { name: "Skip" });
    // exact: the Next.js dev-tools button is also named "...Next...".
    this.nextButton = page.getByRole("button", { name: "Next", exact: true });
    this.engineSelect = page.getByRole("combobox");
    this.tracingSwitch = page.getByLabel("Enable Tracing");
    this.argNames = page.getByPlaceholder("Argument Name");
    this.envNames = page.getByPlaceholder("Variable Name");
    this.addArgumentButton = page.getByRole("button", {
      name: "Add Argument",
    });
    this.addEnvVarButton = page.getByRole("button", {
      name: "Add Environment Variable",
    });
    this.createButton = page.getByRole("button", {
      name: "Create instance",
    });
    this.cpuHint = page.getByText("runs on CPU");
  }

  async open(modelId: string) {
    await this.goto(`/models/launch/${modelId}`);
  }

  tab(name: LaunchTab): Locator {
    return this.page.getByRole("tab", { name, exact: true });
  }

  async selectEngine(name: string) {
    await this.engineSelect.click();
    await this.page.getByRole("option", { name, exact: true }).click();
  }

  /** The "Delete" button next to the last (new) argument row. */
  lastArgDeleteButton(): Locator {
    return this.page
      .locator("div.flex", { has: this.argNames.last() })
      .getByRole("button", { name: "Delete" });
  }

  /** The options of the open engine select (click `engineSelect` first). */
  engineOptions(): Locator {
    return this.page.getByRole("option");
  }
}
