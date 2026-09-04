# UI end-to-end tests

The frontend has a Playwright suite in `frontend/e2e/`.
It drives the real Next.js app in Chromium against a real backend.
There are two tiers:

| Tier      | Backend                                              | Frontend                              | Runs in CI | Typical time |
| --------- | ---------------------------------------------------- | ------------------------------------- | ---------- | ------------ |
| `fast`    | `TEST_MODE=true` (SQLite, seeded catalogs, no cluster) | production build on `:3001`         | yes        | about 30 s   |
| `cluster` | the live backend on `:8000` deploying into kind      | the dev server on `:3000` (or yours) | no         | about 2 min with cached images |

The fast tier never touches a cluster.
The managed backend runs with `KUBECONFIG` set to a path that does not exist,
so every create call the backend forwards to Kubernetes is rejected and the tests assert the UI's error handling instead.
The cluster tier creates real Helm releases and Kubernetes objects and deletes them again.

## Prerequisites

Once per machine:

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm exec playwright install chromium        # add --with-deps on Linux
cd ../backend && uv sync                      # the fast tier starts the backend with uv
```

`helm` must be on `PATH` for the backend to import, and `kubectl` too for the cluster tier.

## Run the fast tier

The simplest way starts both servers for you:

```bash
make ui-e2e
# or
cd frontend && E2E_START_SERVERS=1 pnpm e2e
```

With `E2E_START_SERVERS=1` Playwright:

1. removes any stale `backend/tmp/test_database_*.db` (TEST_MODE ids are deterministic, so the file name repeats),
2. starts `uvicorn` on `:8001` with `TEST_MODE=true`,
3. runs `pnpm build && pnpm start -p 3001` with `AIOPS_BACKEND_URL=http://localhost:8001`,
4. runs every spec under `e2e/fast/`.

The frontend server is reused when one already answers on `:3001`; the backend is always started fresh.
Port `8001` must be free.

To iterate faster, run your own servers and point the tests at them:

```bash
# terminal 1
cd backend && TEST_MODE=true KUBECONFIG=/nonexistent uv run uvicorn app:app --port 8001
# terminal 2
cd frontend && AIOPS_BACKEND_URL=http://localhost:8001 pnpm dev -p 3030
# terminal 3
cd frontend && E2E_BASE_URL=http://localhost:3030 E2E_BACKEND_URL=http://localhost:8001 pnpm e2e
```

Set `KUBECONFIG` to a path that does not exist.
Otherwise the TEST_MODE backend uses your kind cluster and the tests create real jobs.

## Run the cluster tier

Bring the stack up as described in `docs/local-dev.md` (`make kind-up`, `make db-up`, `make backend`, `make frontend`), then:

```bash
make ui-e2e-cluster
# or, against other ports
cd frontend && E2E_BASE_URL=http://localhost:3030 E2E_BACKEND_URL=http://localhost:8000 pnpm e2e:cluster
```

The cluster project runs with one worker, no retries, a 10 minute timeout per test and a 30 second expect timeout.
Each spec cleans up through the API in `test.afterEach`, so a failed run does not leave releases behind.
`helm -n ai-stack list` should not show a release for a test instance after the run.

## Scripts and make targets

| Command                | What it does                                                        |
| ---------------------- | ------------------------------------------------------------------- |
| `pnpm e2e`             | fast project                                                        |
| `pnpm e2e:cluster`     | cluster project, one worker                                         |
| `pnpm e2e:ui`          | fast project in Playwright UI mode                                  |
| `pnpm e2e:report`      | open the last HTML report                                           |
| `make ui-e2e`          | fast project with managed servers (`E2E_START_SERVERS=1`)           |
| `make ui-e2e-cluster`  | cluster project against `FRONTEND_URL` (`:3000`) and `BACKEND_URL` (`:8000`) |

Both make targets accept `ARGS`, for example `make ui-e2e ARGS="--grep theme"`.

## Environment variables

| Variable            | Default                                              | Meaning                                              |
| ------------------- | ---------------------------------------------------- | ---------------------------------------------------- |
| `E2E_BASE_URL`      | `http://localhost:3000`, or `:3001` with managed servers | frontend the browser opens                        |
| `E2E_BACKEND_URL`   | `http://localhost:8000`, or `:8001` with managed servers | backend the `api` fixture calls for setup and polling |
| `E2E_START_SERVERS` | unset                                                | `1` starts the TEST_MODE backend and a built frontend |
| `E2E_RUN_FIXME`     | unset                                                | `1` runs the tests marked `fixme` instead of skipping them |
| `E2E_HELM_NAMESPACE`| `ai-stack`                                           | namespace the cluster tier inspects with `helm` and `kubectl` |
| `CI`                | unset                                                | one retry, two workers, GitHub reporter, no server reuse |

## Layout

```
frontend/
  playwright.config.ts      projects, web servers, reporters
  e2e/
    fixtures.ts             `test` with the console guard, the `api` fixture, helm/kubectl helpers, `fixme()`
    pages/                  page objects; one class per screen, accessible-name locators only
      app-shell.ts          header, theme menu, heading, toasts, delete confirmation
      home.ts  model-catalog.ts  model-details.ts  finetune-form.ts  launch-model.ts
      vector-db-catalog.ts  vector-db-endpoints.ts  notebook-form.ts  notebooks.ts
    fast/                   one spec per scenario, hermetic
    cluster/                one spec per lifecycle, tagged @cluster
```

### Fixtures

- `test` from `e2e/fixtures.ts` extends Playwright's `test`.
  An auto fixture records every `console.error` and uncaught page error and fails the test at the end if any is left.
  Dev-only noise (React DevTools hint, Fast Refresh, favicon) is on the default allowlist.
  A test that expects a failed API call opts in with
  `test.use({ allowedConsoleErrors: [FAILED_RESOURCE] })` in a `describe` block.
- `api` is a `BackendApi` bound to `E2E_BACKEND_URL`.
  It lists and deletes notebooks, vector DB instances and fine-tune jobs, and polls with `waitForNotebookStatus` and `waitForVectorDBReady`.
- `helmReleases()`, `waitForHelmReleaseGone()` and `kubernetesJobs()` shell out to `helm` and `kubectl` for the cluster tier.
- `fixme(reason)` skips a test for a known product bug and records the reason in the report.
  `E2E_RUN_FIXME=1` runs those tests so you can see when a fix has landed; remove the call once the test passes.
- `shortId()` gives a suffix for resource names (`e2e-jupyter-k3x9pq`).

### Tags

Cluster specs are declared with `test.describe("…", { tag: "@cluster" }, …)`.
The `fast` project uses `grepInvert: /@cluster/` and the `cluster` project uses `grep: /@cluster/`, so a spec is never run by the wrong tier.

## Add a scenario

1. Add or extend a page object in `e2e/pages/`.
   Locate elements by role and accessible name (`getByRole`, `getByLabel`, `getByPlaceholder`).
   Use `data-slot` attributes from the shadcn primitives (`[data-slot="card"]`) only for structure that has no role.
   Avoid CSS classes and text that is likely to be reworded.
2. Write `e2e/fast/<scenario>.spec.ts` (or `e2e/cluster/…` with the `@cluster` tag).
   Import `test` and `expect` from `../fixtures`, never from `@playwright/test`, so the console guard and the `api` fixture apply.
   Derive expected data from the API (`await api.models()`) instead of hard-coding catalog contents.
3. If the behaviour is not implemented yet, write the test for the correct behaviour and start it with `fixme("reason")`.
4. Run `pnpm exec tsc --noEmit` and `pnpm lint`; the e2e files are type-checked and linted with the app.

## Debug

- `pnpm e2e:ui` opens the Playwright UI with time travel for the fast tier.
- `pnpm e2e -- --debug --grep "theme"` runs one scenario headed with the inspector.
- Traces are recorded on the first retry (`trace: "on-first-retry"`).
  Force one with `pnpm e2e -- --trace on`, then `pnpm e2e:report` and open the trace from the report.
- Every failure writes `test-results/<test>/error-context.md` with an accessibility snapshot of the page.
- The managed backend's stderr is piped to the Playwright output; its SQLite file is `backend/tmp/test_database_*.db`.
- In CI the HTML report is uploaded as the `playwright-report` artifact.

## Scenarios

Durations are from a local run on Apple silicon; CI is slower.

| Spec (fast tier)              | Covers                                                                                                  | Status                        | Time  |
| ----------------------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------- | ----- |
| `navigation.spec.ts`          | every header link and dropdown item, brand link, active section, no console errors on eight pages       | pass                          | 2 s   |
| `home.spec.ts`                | the four cards and their links                                                                          | pass                          | 1 s   |
| `models-catalog.spec.ts`      | search, category and subcategory filters, combined filters, Import Model dialog, card link              | pass                          | 3 s   |
| `model-details.spec.ts`       | Details tab content, `?tab=` reflects the tab and survives reload, deep link, Launch Model             | pass                          | 4 s   |
| `finetune-form.spec.ts`       | sections and defaults, required fields block the submit, backend rejection toast, stubbed create/list/params/delete flow | pass | 3 s |
| `launch-form.spec.ts`         | the three wizard steps, engine filtering, empty argument name blocks the submit, rejected deploy toast  | pass                          | 3 s   |
| `vector-db-catalog.spec.ts`   | three cards, Launch dialog, Cancel                                                                       | pass; service type `fixme` (no control in the dialog yet) | 1 s   |
| `notebook-form.spec.ts`       | defaults, VS Code hides framework and GPU, GPU count, name rules, out-of-range storage, helper text     | pass                          | 2 s   |
| `error-pages.spec.ts`         | unknown model, unknown notebook, unknown route shows the not-found page                                 | pass                          | 4 s   |
| `theme.spec.ts`               | system default, Light and Dark persist across reloads, back to System                                   | pass                          | 2 s   |
| `develop.spec.ts`             | "Langflow is not configured" card                                                                       | pass                          | 1 s   |
| `mobile.spec.ts`              | no horizontal overflow at 390 px, hamburger menu                                                        | pass                          | 2 s   |

| Spec (cluster tier)           | Covers                                                                                                  | Time      |
| ----------------------------- | ------------------------------------------------------------------------------------------------------- | --------- |
| `vector-db-lifecycle.spec.ts` | launch Qdrant from the catalog, endpoints page lists it, Ready with an endpoint, delete, Helm release gone | 40 s |
| `notebook-lifecycle.spec.ts`  | Jupyter and VS Code: create, details page, Running, delete, list empty                                  | 40 s each |
| `finetune-lifecycle.spec.ts`  | create a job from the UI, Kubernetes Job exists, cluster-derived status, delete, Job gone               | 5 s |

The cluster times assume the images are already on the kind node.
The first pull of a notebook or Qdrant image adds minutes; the tests wait up to 6 minutes for a notebook and 5 for a vector DB.

### Why the fine-tune create is stubbed in the fast tier

The TEST_MODE backend still submits a Kubernetes Job on `POST /models/{id}/finetune`.
Without a cluster it answers 500, and the fast tier asserts that toast.
The list, params, delete and logs interactions therefore run against `page.route` stubs that mirror the real response shapes; the cluster tier runs the real call.
