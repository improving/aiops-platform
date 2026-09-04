import { defineConfig, devices } from "@playwright/test";
import type { E2EOptions } from "./e2e/fixtures";

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

const BACKEND_PORT = 8001;
const FRONTEND_PORT = 3001;
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
    },
    {
      name: "cluster",
      testDir: "./e2e/cluster",
      grep: /@cluster/,
      fullyParallel: false,
      retries: 0,
      timeout: 10 * 60_000,
      expect: { timeout: 30_000 },
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
          env: { TEST_MODE: "true", KUBECONFIG: NO_KUBECONFIG },
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
          },
          reuseExistingServer: !CI,
          timeout: 300_000,
          stdout: "ignore",
          stderr: "pipe",
        },
      ]
    : undefined,
});
