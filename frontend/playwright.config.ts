import { defineConfig, devices } from "@playwright/test";
import type { AuthMode, E2EOptions } from "./e2e/fixtures";

// Two tiers:
//   fast    - runs against a TEST_MODE backend (SQLite, seeded catalogs, no
//             cluster). Hermetic; this is what CI runs.
//   cluster - runs against the real local stack (backend on 8000 deploying
//             into kind). Serial, long timeouts, opt-in.
//
// Servers: set E2E_START_SERVERS=1 to have Playwright start the TEST_MODE
// backend on 8001 and a production frontend on 3001 that proxies to it.
// Otherwise point E2E_BASE_URL / E2E_BACKEND_URL at servers you run yourself.

const CI = !!process.env.CI;
const START_SERVERS = process.env.E2E_START_SERVERS === "1";

// E2E_BACKEND_PORT / E2E_FRONTEND_PORT move the managed servers, so two
// checkouts (worktrees) can run the fast tier at the same time.
const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 8001);
const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT ?? 3001);
const managedBackendURL = `http://localhost:${BACKEND_PORT}`;
const managedFrontendURL = `http://localhost:${FRONTEND_PORT}`;

const baseURL =
  process.env.E2E_BASE_URL ??
  (START_SERVERS ? managedFrontendURL : "http://localhost:3000");
const backendURL =
  process.env.E2E_BACKEND_URL ??
  (START_SERVERS ? managedBackendURL : "http://localhost:8000");

// A path that does not exist, so the TEST_MODE backend never talks to a real
// cluster even when the developer has a kubeconfig for kind.
const NO_KUBECONFIG = "/nonexistent/e2e-kubeconfig";

// Whether the `api` fixture (in e2e/fixtures.ts) attaches a bearer token.
// E2E_AUTH_MODE overrides both projects explicitly; otherwise AUTH_MODE (the
// same variable the backend and the managed frontend read) is honoured when
// it names a mode; otherwise each project falls back to what its backend
// actually needs: the fast project's managed backend always runs with
// AUTH_MODE=disabled (below), and the cluster project talks to the real,
// OIDC-enforcing backend.
function authModeFor(projectDefault: AuthMode): AuthMode {
  const value = process.env.E2E_AUTH_MODE ?? process.env.AUTH_MODE;
  return value === "oidc" || value === "disabled" ? value : projectDefault;
}

export default defineConfig<E2EOptions>({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  workers: CI ? 2 : undefined,
  reporter: CI
    ? [["github"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    backendURL,
    trace: "on-first-retry",
    ...devices["Desktop Chrome"],
  },
  projects: [
    {
      name: "fast",
      testDir: "./e2e/fast",
      grepInvert: /@cluster/,
      timeout: 60_000,
      // First navigations on a cold production server exceed Playwright's
      // 5 s default on a two-core CI runner.
      expect: { timeout: 15_000 },
    },
    {
      // Logs alice, bob and admin into Keycloak once and saves their
      // sessions to playwright/.auth/<user>.json (see e2e/auth.setup.ts).
      // The cluster project depends on this and runs it automatically, so
      // `pnpm e2e:cluster --grep ...` still regenerates fresh state; only a
      // `--no-deps` or a `--project=cluster` filtered to a project other
      // than "setup" skips it, per Playwright's project dependency rules.
      name: "setup",
      testDir: "./e2e",
      testMatch: /auth\.setup\.ts/,
      timeout: 60_000,
      use: { ignoreHTTPSErrors: true },
    },
    {
      name: "cluster",
      testDir: "./e2e/cluster",
      grep: /@cluster/,
      fullyParallel: false,
      retries: 0,
      timeout: 10 * 60_000,
      expect: { timeout: 30_000 },
      dependencies: ["setup"],
      use: {
        // Gateway TLS uses the local dev CA (infra/local/ca/ca.crt), which
        // browsers and Playwright's request contexts do not trust by
        // default.
        ignoreHTTPSErrors: true,
        // Every cluster spec is signed in as alice by default; a test that
        // needs a second identity (e.g. to confirm bob gets 403) uses the
        // `asUser("bob")` fixture instead of overriding this per test.
        storageState: "playwright/.auth/alice.json",
        authMode: authModeFor("oidc"),
      },
    },
  ],
  webServer: START_SERVERS
    ? [
        {
          // TEST_MODE ids are deterministic, so the SQLite file name repeats
          // between runs; remove it to start from the seeded catalogs only.
          command: `rm -f tmp/test_database_*.db && uv run uvicorn app:app --port ${BACKEND_PORT}`,
          cwd: "../backend",
          url: `${managedBackendURL}/health`,
          env: {
            TEST_MODE: "true",
            AUTH_MODE: "disabled",
            KUBECONFIG: NO_KUBECONFIG,
            AIOPS_CHAT_MOCK: "true",
            AIOPS_SECRET_STORE: "memory",
          },
          // A fresh SQLite per run is the point of TEST_MODE; never reuse.
          reuseExistingServer: false,
          timeout: 120_000,
          stdout: "ignore",
          stderr: "pipe",
        },
        {
          command: `pnpm build && pnpm start -p ${FRONTEND_PORT}`,
          url: managedFrontendURL,
          env: {
            AIOPS_BACKEND_URL: managedBackendURL,
            NEXT_PUBLIC_AIOPS_BACKEND_URL: managedBackendURL,
            // The fast tier has no Keycloak: the proxy neither redirects nor
            // adds a bearer, and the build hides the user menu.
            AUTH_MODE: "disabled",
            NEXT_PUBLIC_AUTH_MODE: "disabled",
          },
          reuseExistingServer: !CI,
          timeout: 300_000,
          stdout: "ignore",
          stderr: "pipe",
        },
      ]
    : undefined,
});
