import {
  test as base,
  expect,
  request as playwrightRequest,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { execFileSync } from "node:child_process";

// ---------------------------------------------------------------------------
// Options
// ---------------------------------------------------------------------------

export type E2EOptions = {
  /** Backend base URL (no trailing slash), used by the `api` fixture. */
  backendURL: string;
  /**
   * Console/page errors that match one of these patterns do not fail the
   * test. Tests that expect an API error add `/Failed to load resource/`.
   */
  allowedConsoleErrors: RegExp[];
};

/** Dev-only noise that never indicates a product bug. */
export const DEFAULT_ALLOWED_CONSOLE_ERRORS: RegExp[] = [
  /Download the React DevTools/,
  /\[Fast Refresh\]/,
  /favicon\.ico/,
];

/** Chromium logs failed fetches as console errors; expected API errors opt in. */
export const FAILED_RESOURCE = /Failed to load resource/;

// ---------------------------------------------------------------------------
// Backend API helper
// ---------------------------------------------------------------------------

export type NotebookRecord = {
  id: string;
  name: string;
  type: string;
  status: string | null;
  ready: boolean;
  endpoint: string | null;
};

export type VectorDBInstanceRecord = {
  id: string;
  vectorDB: { id: string; name: string; chart_name: string };
  status: string | null;
  ready: boolean;
  endpoint: string | null;
};

export type ModelRecord = {
  id: string;
  name: string;
  modelId: string;
  category: string;
  subcategory: string;
};

export type FineTuneJobRecord = {
  id: string;
  name: string;
  status: string | null;
};

export class BackendApi {
  constructor(
    readonly request: APIRequestContext,
    readonly baseURL: string
  ) {}

  private url(path: string) {
    return `${this.baseURL}/v1alpha1${path}`;
  }

  async models(): Promise<ModelRecord[]> {
    const res = await this.request.get(this.url("/models"));
    expect(res.ok(), `GET /models -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async vectorDBs(): Promise<{ id: string; name: string; chart_name: string }[]> {
    const res = await this.request.get(this.url("/vectordb"));
    expect(res.ok(), `GET /vectordb -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async notebooks(): Promise<NotebookRecord[]> {
    const res = await this.request.get(this.url("/notebooks"));
    expect(res.ok(), `GET /notebooks -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async notebook(id: string): Promise<NotebookRecord | null> {
    const res = await this.request.get(this.url(`/notebooks/${id}`));
    if (res.status() === 404) return null;
    expect(res.ok(), `GET /notebooks/${id} -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async deleteNotebook(id: string): Promise<void> {
    const res = await this.request.delete(this.url(`/notebooks/${id}`));
    expect([200, 204, 404]).toContain(res.status());
  }

  async vectorDBInstances(): Promise<VectorDBInstanceRecord[]> {
    const res = await this.request.get(this.url("/vectordb_instances"));
    expect(
      res.ok(),
      `GET /vectordb_instances -> ${res.status()}`
    ).toBeTruthy();
    return res.json();
  }

  async vectorDBInstance(id: string): Promise<VectorDBInstanceRecord | null> {
    const res = await this.request.get(this.url(`/vectordb_instances/${id}`));
    if (res.status() === 404) return null;
    expect(res.ok()).toBeTruthy();
    return res.json();
  }

  async deleteVectorDBInstance(id: string): Promise<void> {
    const res = await this.request.delete(
      this.url(`/vectordb_instances/${id}`)
    );
    expect([200, 204, 404]).toContain(res.status());
  }

  async fineTuneJobs(modelId: string): Promise<FineTuneJobRecord[]> {
    const res = await this.request.get(this.url(`/models/${modelId}/finetune`));
    expect(res.ok(), `GET finetune -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async deleteFineTuneJob(modelId: string, jobId: string): Promise<void> {
    const res = await this.request.delete(
      this.url(`/models/${modelId}/finetune/${jobId}`)
    );
    expect([200, 204, 404]).toContain(res.status());
  }

  /** Poll until the notebook reports `status` (default "Running"). */
  async waitForNotebookStatus(
    id: string,
    status = "Running",
    timeoutMs = 6 * 60_000
  ): Promise<NotebookRecord> {
    let last: NotebookRecord | null = null;
    await expect
      .poll(
        async () => {
          last = await this.notebook(id);
          return last?.status ?? null;
        },
        {
          message: `notebook ${id} did not reach status ${status}`,
          timeout: timeoutMs,
          intervals: [5_000],
        }
      )
      .toBe(status);
    return last!;
  }

  /** Poll until the vector DB instance is ready and has an endpoint. */
  async waitForVectorDBReady(
    id: string,
    timeoutMs = 5 * 60_000
  ): Promise<VectorDBInstanceRecord> {
    let last: VectorDBInstanceRecord | null = null;
    await expect
      .poll(
        async () => {
          last = await this.vectorDBInstance(id);
          return !!last?.ready && !!last?.endpoint;
        },
        {
          message: `vector DB instance ${id} did not become ready`,
          timeout: timeoutMs,
          intervals: [5_000],
        }
      )
      .toBe(true);
    return last!;
  }
}

// ---------------------------------------------------------------------------
// Helm helper (cluster tier only)
// ---------------------------------------------------------------------------

export const HELM_NAMESPACE = process.env.E2E_HELM_NAMESPACE ?? "ai-stack";

/** Names of the Helm releases in the platform namespace. */
export function helmReleases(namespace = HELM_NAMESPACE): string[] {
  const out = execFileSync("helm", ["-n", namespace, "list", "-o", "json"], {
    encoding: "utf8",
  });
  const releases = JSON.parse(out) as { name: string }[];
  return releases.map((r) => r.name);
}

/** Poll until no release name contains `fragment`. Uninstall is async. */
export async function waitForHelmReleaseGone(
  fragment: string,
  timeoutMs = 120_000
) {
  await expect
    .poll(() => helmReleases().filter((n) => n.includes(fragment)), {
      message: `helm release containing "${fragment}" was not removed`,
      timeout: timeoutMs,
      intervals: [5_000],
    })
    .toEqual([]);
}

// ---------------------------------------------------------------------------
// Console guard
// ---------------------------------------------------------------------------

function attachConsoleGuard(page: Page, allowed: RegExp[]) {
  const errors: string[] = [];
  const isAllowed = (text: string) => allowed.some((re) => re.test(text));
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (!isAllowed(text)) errors.push(`console.error: ${text}`);
  });
  page.on("pageerror", (err) => {
    const text = `${err.name}: ${err.message}`;
    if (!isAllowed(text)) errors.push(`pageerror: ${text}`);
  });
  return errors;
}

// ---------------------------------------------------------------------------
// Test
// ---------------------------------------------------------------------------

type Fixtures = {
  api: BackendApi;
  consoleErrors: string[];
};

export const test = base.extend<E2EOptions & Fixtures>({
  backendURL: ["http://localhost:8000", { option: true }],
  allowedConsoleErrors: [DEFAULT_ALLOWED_CONSOLE_ERRORS, { option: true }],

  api: async ({ backendURL }, provide) => {
    const ctx = await playwrightRequest.newContext({ baseURL: backendURL });
    await provide(new BackendApi(ctx, backendURL));
    await ctx.dispose();
  },

  // Auto fixture: any console error or uncaught page error fails the test.
  consoleErrors: [
    async ({ page, allowedConsoleErrors }, provide) => {
      const errors = attachConsoleGuard(page, allowedConsoleErrors);
      await provide(errors);
      expect
        .soft(errors, "unexpected browser console errors")
        .toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

/** Short random suffix for resource names created by the tests. */
export function shortId(): string {
  return Math.random().toString(36).slice(2, 8);
}
