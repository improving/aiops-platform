import {
  test as base,
  expect,
  request as playwrightRequest,
  type APIRequestContext,
  type APIResponse,
  type BrowserContext,
  type Page,
} from "@playwright/test";
import { execFileSync } from "node:child_process";
import * as path from "node:path";

// ---------------------------------------------------------------------------
// Options
// ---------------------------------------------------------------------------

export type AuthMode = "oidc" | "disabled";

export type E2EOptions = {
  /** Backend base URL (no trailing slash), used by the `api` fixture. */
  backendURL: string;
  /**
   * Whether the `api` fixture sends a bearer token. "disabled" matches the
   * fast project (no Keycloak, `AUTH_MODE=disabled` on the managed backend);
   * "oidc" matches the cluster project (a real backend enforcing 401
   * without one). Playwright.config.ts sets this per project; the default
   * here only applies when a spec runs outside a project (rare).
   */
  authMode: AuthMode;
  /**
   * Console/page errors that match one of these patterns do not fail the
   * test. Tests that expect an API error add `/Failed to load resource/`.
   *
   * Keep a `test.use({ allowedConsoleErrors: [...] })` override to ONE
   * pattern (combine with `|`): Playwright treats any array whose second
   * element is an object, a RegExp included, as a `[value, options]`
   * fixture tuple and would keep only the first entry.
   */
  allowedConsoleErrors: RegExp[];
};

/** One of the users `e2e/auth.setup.ts` logs in and saves storage state for. */
export type E2EUser = "alice" | "bob" | "admin";

/** The X-Dev-User identities of the fast tier (backend/auth/dev_users.py). */
export type DevUser = "dev" | "alice" | "bob" | "viewer" | "outsider";

/** Cookie names shared with src/lib/orgCookie.ts (kept literal here so the
 * e2e files stay independent of the app's module graph). */
export const DEV_USER_COOKIE = "aiops_dev_user";
export const ORG_COOKIE = "aiops_org";

// Resolved from this file's location (frontend/e2e/fixtures.ts), not the
// process cwd, so it is correct however the test runner is invoked.
const AUTH_STATE_DIR = path.resolve(__dirname, "..", "playwright", ".auth");

/** Absolute path to the saved storage state for `user`. */
export function authStatePath(user: E2EUser): string {
  return path.join(AUTH_STATE_DIR, `${user}.json`);
}

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

export type EngineRecord = {
  id: string;
  name: string;
  llm_support: boolean;
  cpu: boolean;
  default_args: { name: string; defaultValue: string }[];
  default_config: { name: string; defaultValue: string }[];
};

// GET /v1alpha1/models/{id}/serving-options (backend/schemas/serving_option.py):
// engine_id is null for a hosted option (e.g. "openrouter"), which has no
// engines row and no chart to launch; the launch wizard renders only
// options with one.
export type ServingOptionRecord = {
  id: string;
  engine: string;
  reference: string;
  default_args: Record<string, string> | null;
  engine_id: string | null;
  cpu: boolean | null;
};

export type InferenceInstanceRecord = {
  id: string;
  ready: boolean;
  status: string | null;
  endpoint: string | null;
  model: { id: string; name: string; modelId: string };
  engine: { id: string; name: string };
  litellm_model_name?: string | null;
};

/** GET /v1alpha1/chat/targets: what the caller may chat, embed or rerank
 * against (backend/api/chat.py list_targets). */
export type ChatTargetRecord = {
  name: string;
  label: string;
  capability: string;
  instance_id: string | null;
  provider_id: string | null;
  model: string;
  engine: string;
  ready: boolean;
  via: string;
};

// GET /v1alpha1/providers (backend/api/providers.py): a hosted provider,
// without its API key.
export type ProviderRecord = {
  id: string;
  kind: string;
  name: string;
  base_url: string | null;
  enabled: boolean;
  has_key: boolean;
  models: {
    id: string;
    model: string;
    display_name: string;
    litellm_model_name: string;
    capability: string;
    enabled: boolean;
  }[];
};

// GET /v1alpha1/registry (backend/api/registry.py): one model row,
// including its serving options (backend/schemas/serving_option.py).
export type RegistryEntryRecord = {
  id: string;
  name: string;
  modelId: string;
  source: string;
  source_id: string | null;
  status: string;
  serving_options: { id: string; engine: string; reference: string }[] | null;
};

// GET/PUT /v1alpha1/organizations/current/{spend,budget}.
export type OrgSpendRecord = {
  team_id: string | null;
  spend: number;
  max_budget: number | null;
  budget_reset_at: string | null;
  budget_usd: number | null;
};

// GET /v1alpha1/organizations and /organizations/current
// (backend/api/organizations.py).
export type OrganizationRecord = {
  id: string;
  slug: string;
  name: string;
  role: "admin" | "member" | "viewer";
};

export type MyOrganizationsRecord = {
  organizations: OrganizationRecord[];
  active: string;
};

export type CurrentOrganizationRecord = OrganizationRecord & {
  budget_usd: number | null;
  member_count: number;
  is_platform_admin: boolean;
};

/** OIDC settings for the client-credentials grant the `api` fixture uses. */
const OIDC_ISSUER =
  process.env.OIDC_ISSUER ?? "https://auth.127.0.0.1.nip.io/realms/aiops";
const AUTOMATION_CLIENT_ID =
  process.env.AUTOMATION_CLIENT_ID ?? "aiops-automation";
const AUTOMATION_CLIENT_SECRET =
  process.env.AUTOMATION_CLIENT_SECRET ?? "dev-automation-secret";

export class BackendApi {
  /** Cached bearer token; null once fetched with authMode "disabled". */
  private token: string | null = null;
  private tokenPromise: Promise<string | null> | null = null;

  constructor(
    readonly request: APIRequestContext,
    readonly baseURL: string,
    readonly authMode: AuthMode = "disabled",
    readonly extraHeaders: Record<string, string> = {}
  ) {}

  /**
   * The same API with extra headers on every call (X-Org, a token bearer).
   * Through `userApi` the proxy replaces it with the `aiops_org` cookie
   * (src/proxy.ts), so an `X-Org` header here only works against the
   * direct `api` fixture; to pin an organization through the proxy, use
   * a cookie-scoped context instead (see `orgScopedApi` in
   * `e2e/cluster/tenancy-isolation.spec.ts`).
   */
  withHeaders(headers: Record<string, string>): BackendApi {
    return new BackendApi(this.request, this.baseURL, this.authMode, {
      ...this.extraHeaders,
      ...headers,
    });
  }

  private url(path: string) {
    return `${this.baseURL}/v1alpha1${path}`;
  }

  /**
   * A client-credentials token from the automation client, fetched once per
   * `BackendApi` instance (test worker) and reused. `ignoreHTTPSErrors`
   * trusts the local dev CA on the token endpoint the same way the cluster
   * project trusts it on the gateway.
   */
  private async fetchToken(): Promise<string> {
    const ctx = await playwrightRequest.newContext({
      ignoreHTTPSErrors: true,
    });
    try {
      const res = await ctx.post(
        `${OIDC_ISSUER}/protocol/openid-connect/token`,
        {
          form: {
            grant_type: "client_credentials",
            client_id: AUTOMATION_CLIENT_ID,
            client_secret: AUTOMATION_CLIENT_SECRET,
          },
        }
      );
      expect(
        res.ok(),
        `POST ${OIDC_ISSUER}/protocol/openid-connect/token -> ${res.status()}`
      ).toBeTruthy();
      const body = (await res.json()) as { access_token: string };
      return body.access_token;
    } finally {
      await ctx.dispose();
    }
  }

  /** Re-fetches and caches the token; call again after a call answers 401. */
  private async refreshToken(): Promise<string | null> {
    if (this.authMode === "disabled") return null;
    this.tokenPromise = this.fetchToken();
    this.token = await this.tokenPromise;
    return this.token;
  }

  private async authHeaders(): Promise<Record<string, string>> {
    // A caller-supplied bearer (a personal token) wins over the automation
    // token, and a 401 on it must surface instead of being retried.
    if (this.extraHeaders.Authorization) return {};
    if (this.authMode === "disabled") return {};
    if (!this.tokenPromise) this.tokenPromise = this.fetchToken();
    this.token = await this.tokenPromise;
    return this.token ? { Authorization: `Bearer ${this.token}` } : {};
  }

  /** GET/DELETE/POST/PUT with the bearer header, retried once after a 401. */
  private async send(
    method: "GET" | "DELETE" | "POST" | "PUT",
    path: string,
    body?: object
  ): Promise<APIResponse> {
    const call = async (headers: Record<string, string>) => {
      if (method === "GET")
        return this.request.get(this.url(path), { headers });
      if (method === "DELETE")
        return this.request.delete(this.url(path), { headers });
      if (method === "PUT")
        return this.request.put(this.url(path), { headers, data: body });
      return this.request.post(this.url(path), { headers, data: body });
    };
    let res = await call({
      ...this.extraHeaders,
      ...(await this.authHeaders()),
    });
    if (
      res.status() === 401 &&
      this.authMode !== "disabled" &&
      !this.extraHeaders.Authorization
    ) {
      const token = await this.refreshToken();
      res = await call({
        ...this.extraHeaders,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      });
    }
    return res;
  }

  /** A raw GET, for asserting a status (403 for another user's resource). */
  get(path: string): Promise<APIResponse> {
    return this.send("GET", path);
  }

  /** Raw POST and DELETE, for asserting a status or reading a body. */
  post(path: string, body?: object): Promise<APIResponse> {
    return this.send("POST", path, body);
  }

  remove(path: string): Promise<APIResponse> {
    return this.send("DELETE", path);
  }

  async organizations(): Promise<MyOrganizationsRecord> {
    const res = await this.send("GET", "/organizations");
    expect(res.ok(), `GET /organizations -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async currentOrganization(): Promise<CurrentOrganizationRecord> {
    const res = await this.send("GET", "/organizations/current");
    expect(
      res.ok(),
      `GET /organizations/current -> ${res.status()}`
    ).toBeTruthy();
    return res.json();
  }

  async models(): Promise<ModelRecord[]> {
    const res = await this.send("GET", "/models");
    expect(res.ok(), `GET /models -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async engines(): Promise<EngineRecord[]> {
    const res = await this.send("GET", "/engines");
    expect(res.ok(), `GET /engines -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async servingOptions(modelId: string): Promise<ServingOptionRecord[]> {
    const res = await this.send("GET", `/models/${modelId}/serving-options`);
    expect(
      res.ok(),
      `GET /models/${modelId}/serving-options -> ${res.status()}`
    ).toBeTruthy();
    return res.json();
  }

  async vectorDBs(): Promise<
    { id: string; name: string; chart_name: string }[]
  > {
    const res = await this.send("GET", "/vectordb");
    expect(res.ok(), `GET /vectordb -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async notebooks(): Promise<NotebookRecord[]> {
    const res = await this.send("GET", "/notebooks");
    expect(res.ok(), `GET /notebooks -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async notebook(id: string): Promise<NotebookRecord | null> {
    const res = await this.send("GET", `/notebooks/${id}`);
    if (res.status() === 404) return null;
    expect(res.ok(), `GET /notebooks/${id} -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async deleteNotebook(id: string): Promise<void> {
    const res = await this.send("DELETE", `/notebooks/${id}`);
    expect([200, 204, 404]).toContain(res.status());
  }

  async vectorDBInstances(): Promise<VectorDBInstanceRecord[]> {
    const res = await this.send("GET", "/vectordb_instances");
    expect(res.ok(), `GET /vectordb_instances -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async vectorDBInstance(id: string): Promise<VectorDBInstanceRecord | null> {
    const res = await this.send("GET", `/vectordb_instances/${id}`);
    if (res.status() === 404) return null;
    expect(res.ok()).toBeTruthy();
    return res.json();
  }

  async deleteVectorDBInstance(id: string): Promise<void> {
    const res = await this.send("DELETE", `/vectordb_instances/${id}`);
    expect([200, 204, 404]).toContain(res.status());
  }

  async fineTuneJobs(modelId: string): Promise<FineTuneJobRecord[]> {
    const res = await this.send("GET", `/models/${modelId}/finetune`);
    expect(res.ok(), `GET finetune -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async deleteFineTuneJob(modelId: string, jobId: string): Promise<void> {
    const res = await this.send(
      "DELETE",
      `/models/${modelId}/finetune/${jobId}`
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

  async inferenceInstances(): Promise<InferenceInstanceRecord[]> {
    const res = await this.send("GET", "/inferenceInstance");
    expect(res.ok(), `GET /inferenceInstance -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async inferenceInstance(id: string): Promise<InferenceInstanceRecord | null> {
    const res = await this.send("GET", `/inferenceInstance/${id}`);
    if (res.status() === 404) return null;
    expect(res.ok()).toBeTruthy();
    return res.json();
  }

  async createInferenceInstance(
    body: object
  ): Promise<InferenceInstanceRecord> {
    const res = await this.send("POST", "/inferenceInstance", body);
    expect(
      res.status(),
      `POST /inferenceInstance -> ${res.status()} ${await res.text()}`
    ).toBe(201);
    return res.json();
  }

  async deleteInferenceInstance(id: string): Promise<void> {
    const res = await this.send("DELETE", `/inferenceInstance/${id}`);
    expect([200, 204, 404]).toContain(res.status());
  }

  async chatTargets(): Promise<ChatTargetRecord[]> {
    const res = await this.send("GET", "/chat/targets");
    expect(res.ok(), `GET /chat/targets -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async providers(): Promise<ProviderRecord[]> {
    const res = await this.send("GET", "/providers");
    expect(res.ok(), `GET /providers -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async deleteProvider(id: string): Promise<void> {
    const res = await this.send("DELETE", `/providers/${id}`);
    expect([200, 204, 404]).toContain(res.status());
  }

  // "disabled" auth (the fast tier) maps every request to the TEST_MODE
  // dev admin, so this sees every status, not just published.
  async registryEntries(): Promise<RegistryEntryRecord[]> {
    const res = await this.send("GET", "/registry");
    expect(res.ok(), `GET /registry -> ${res.status()}`).toBeTruthy();
    return res.json();
  }

  async deleteRegistryEntry(id: string): Promise<void> {
    const res = await this.send("DELETE", `/registry/${id}`);
    expect([200, 204, 404, 409]).toContain(res.status());
  }

  async orgSpend(): Promise<OrgSpendRecord> {
    const res = await this.send("GET", "/organizations/current/spend");
    expect(
      res.ok(),
      `GET /organizations/current/spend -> ${res.status()}`
    ).toBeTruthy();
    return res.json();
  }

  async embeddings(model: string, input: string[]): Promise<number[][]> {
    const res = await this.send("POST", "/embeddings", { model, input });
    expect(res.ok(), `POST /embeddings -> ${res.status()}`).toBeTruthy();
    return (await res.json()).data.map(
      (d: { embedding: number[] }) => d.embedding
    );
  }

  /** Poll until the inference instance is ready and has an endpoint. */
  async waitForInferenceReady(
    id: string,
    timeoutMs = 12 * 60_000
  ): Promise<InferenceInstanceRecord> {
    let last: InferenceInstanceRecord | null = null;
    await expect
      .poll(
        async () => {
          last = await this.inferenceInstance(id);
          return !!last?.ready && !!last?.endpoint;
        },
        {
          message: `inference instance ${id} did not become ready`,
          timeout: timeoutMs,
          intervals: [10_000],
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

/** Names of the Kubernetes Jobs in the platform namespace. */
export function kubernetesJobs(namespace = HELM_NAMESPACE): string[] {
  const out = execFileSync(
    "kubectl",
    [
      "-n",
      namespace,
      "get",
      "jobs",
      "-o",
      "jsonpath={.items[*].metadata.name}",
    ],
    { encoding: "utf8" }
  );
  return out.split(/\s+/).filter(Boolean);
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
  /**
   * A logged-in `BrowserContext` for `name`, restored from the storage
   * state `e2e/auth.setup.ts` saved. Contexts are created lazily and cached
   * per test, and closed in teardown. Cluster specs default to alice via
   * the project's `storageState`; use this fixture to act as a second user
   * (bob) in the same test, e.g. to confirm they get 403 on alice's
   * resources.
   */
  asUser: (name: E2EUser | DevUser) => Promise<BrowserContext>;
  /**
   * A `BackendApi` that calls `/api/v1alpha1` through the UI proxy with the
   * `asUser(name)` session, so the backend sees that user's own bearer
   * token (`src/proxy.ts` adds it). The automation user behind `api` is a
   * plain member: it cannot see alice's notebooks (owner or admin only)
   * and cannot delete what she created. Use `userApi("alice")` to look up
   * and poll her notebooks and `userApi("admin")` for cleanup.
   */
  userApi: (name: E2EUser | DevUser) => Promise<BackendApi>;
};

export const test = base.extend<E2EOptions & Fixtures>({
  backendURL: ["http://localhost:8000", { option: true }],
  // Only used when a spec runs outside a project's `use` block; both
  // projects in playwright.config.ts set this explicitly.
  authMode: ["disabled", { option: true }],
  allowedConsoleErrors: [DEFAULT_ALLOWED_CONSOLE_ERRORS, { option: true }],

  api: async ({ backendURL, authMode }, provide) => {
    // ignoreHTTPSErrors is a no-op against the plain-http backendURL (fast
    // tier) and lets the cluster tier hit gateway https:// endpoints signed
    // by the local dev CA without importing it into Node's trust store.
    const ctx = await playwrightRequest.newContext({
      baseURL: backendURL,
      ignoreHTTPSErrors: true,
    });
    await provide(new BackendApi(ctx, backendURL, authMode));
    await ctx.dispose();
  },

  asUser: async ({ browser, authMode, baseURL }, provide) => {
    const cache = new Map<string, BrowserContext>();
    const factory = async (name: E2EUser | DevUser) => {
      let ctx = cache.get(name);
      if (!ctx) {
        if (authMode === "disabled") {
          // Fast tier: no Keycloak; the cookie becomes X-Dev-User in
          // src/proxy.ts and picks a fixed dev identity on the backend.
          // baseURL is not inherited by browser.newContext(); pass it so
          // relative page.goto("/...") works on these contexts too.
          ctx = await browser.newContext({ baseURL });
          await ctx.addCookies([
            { name: DEV_USER_COOKIE, value: name, url: baseURL! },
          ]);
        } else {
          ctx = await browser.newContext({
            baseURL,
            storageState: authStatePath(name as E2EUser),
            ignoreHTTPSErrors: true,
          });
        }
        cache.set(name, ctx);
      }
      return ctx;
    };
    await provide(factory);
    for (const ctx of cache.values()) await ctx.close();
  },

  userApi: async ({ asUser, baseURL }, provide) => {
    expect(baseURL, "userApi needs a baseURL").toBeTruthy();
    const proxyURL = `${baseURL!.replace(/\/$/, "")}/api`;
    await provide(async (name: E2EUser | DevUser) => {
      const ctx = await asUser(name);
      // "disabled": no bearer of its own; the proxy adds the session's.
      return new BackendApi(ctx.request, proxyURL, "disabled");
    });
  },

  // Auto fixture: any console error or uncaught page error fails the test.
  consoleErrors: [
    async ({ page, allowedConsoleErrors }, provide) => {
      const errors = attachConsoleGuard(page, allowedConsoleErrors);
      await provide(errors);
      expect.soft(errors, "unexpected browser console errors").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

/**
 * Mark a test as pending on a known product bug. It is skipped and reported
 * as "fixme" until E2E_RUN_FIXME=1 is set, which runs it so you can see
 * whether the fix has landed.
 */
export function fixme(reason: string) {
  test.fixme(process.env.E2E_RUN_FIXME !== "1", reason);
}

/** Short random suffix for resource names created by the tests. */
export function shortId(): string {
  return Math.random().toString(36).slice(2, 8);
}
