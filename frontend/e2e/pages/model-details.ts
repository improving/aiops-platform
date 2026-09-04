import type { Locator, Page } from "@playwright/test";
import { AppShell } from "./app-shell";

export type ModelTab = "Details" | "Adapters" | "Fine-tune Jobs";

export class ModelDetailsPage extends AppShell {
  constructor(page: Page) {
    super(page);
  }

  async open(modelId: string, tab?: string) {
    await this.goto(`/models/${modelId}${tab ? `?tab=${tab}` : ""}`);
  }

  tab(name: ModelTab): Locator {
    return this.page.getByRole("tab", { name, exact: true });
  }

  /** The active tab panel. */
  panel(): Locator {
    return this.page.getByRole("tabpanel");
  }

  /** The table inside the active tab panel (Adapters, Fine-tune Jobs). */
  table(): Locator {
    return this.panel().getByRole("table");
  }

  /** Body rows of the active table (header row excluded). */
  bodyRows(): Locator {
    return this.table().locator("tbody tr");
  }

  jobRow(name: string): Locator {
    return this.bodyRows().filter({ hasText: name });
  }

  // The row action buttons are icon-only and have no accessible name, so
  // they are addressed by column and variant. See docs/testing.md.

  /** The "Logs" button in a Fine-tune Jobs row (column 5). */
  jobLogsButton(row: Locator): Locator {
    return row.getByRole("cell").nth(4).getByRole("button");
  }

  /** The "Params" button in a Fine-tune Jobs row (column 4). */
  jobParamsButton(row: Locator): Locator {
    return row.getByRole("cell").nth(3).getByRole("button");
  }

  /** The delete button in any table row. */
  rowDeleteButton(row: Locator): Locator {
    return row.locator('button[data-variant="destructive"]');
  }
}
