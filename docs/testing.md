# UI end-to-end tests

The frontend has a Playwright suite in `frontend/e2e/`.
It drives the real Next.js app in Chromium against a real backend.
There are two tiers:

| Tier      | Backend                                              | Frontend                              | Runs in CI | Typical time |
| --------- | ---------------------------------------------------- | ------------------------------------- | ---------- | ------------ |
| `fast`    | `TEST_MODE=true` (SQLite, seeded catalogs, no cluster) | production build on `:3001`         | yes        | about 30 s   |
| `cluster` | the live backend on `:8000` deploying into kind      | the dev server on `:3000` (or yours) | no         | about 3.5 min with cached images |

The fast tier never touches a cluster.
The managed backend runs with `KUBECONFIG` set to a path that does not exist,
so every create call the backend forwards to Kubernetes is rejected and the tests assert the UI's error handling instead.
The cluster tier creates real Helm releases and Kubernetes objects and deletes them again.

The two tiers also differ in authentication.
The fast tier runs both managed servers with `AUTH_MODE=disabled`:
there is no Keycloak, the proxy neither redirects nor adds a bearer token, and the UI hides the user menu.
The cluster tier runs against the real stack (`AUTH_MODE=oidc`):
every spec is signed in through a real Keycloak login, and the backend rejects any call without a valid bearer token.
See "Authentication" below.

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

Bring the stack up as described in `docs/local-dev.md`
(`make kind-up`, `make gateway-up`, `make auth-up`, `make db-up`, `make backend`, `make frontend`), then:

```bash
make ui-e2e-cluster
# or, against other ports
cd frontend && E2E_BASE_URL=http://localhost:3030 E2E_BACKEND_URL=http://localhost:8000 pnpm e2e:cluster
```

The cluster project runs with one worker, no retries, a 10 minute timeout per test and a 30 second expect timeout.
Each spec cleans up through the API in `test.afterEach`, so a failed run does not leave releases behind;
the cleanup runs as admin through `userApi("admin")`, because the automation user may not delete what alice created.
`helm -n ai-stack list` should show nothing but `langflow` after the run.

Every cluster spec runs signed in.
The project depends on a `setup` project (`e2e/auth.setup.ts`) that logs alice, bob and admin into Keycloak once
and saves each session to `playwright/.auth/<user>.json`;
Playwright runs `setup` automatically before `cluster`, so a plain `make ui-e2e-cluster` or `pnpm e2e:cluster`
always starts from a fresh login.
The `cluster` project's `storageState` defaults every test to alice;
a test that needs a second identity — to confirm bob gets 403 on alice's resources, for example —
asks for a separate context with the `asUser("bob")` fixture instead of overriding `storageState` per test.

A filtered run (`--grep`, `--project=cluster --no-deps`) can still skip the `setup` project,
so a stale or missing `playwright/.auth/*.json` from a partial run is expected in that case;
run the `cluster` project once without a filter to regenerate it.
Keycloak restarting invalidates every saved session too:
the refresh token in it no longer exists, `RefreshAccessTokenError` fires on the next Auth.js refresh,
and the affected spec is redirected to `/login`.
`make auth-up` restarts Keycloak, so re-run the cluster tier's `setup` project (or the whole tier) after it.

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
| `E2E_AUTH_MODE`     | derived (see below)                                  | overrides whether the `api` fixture sends a bearer token: `oidc` or `disabled` |
| `AUTH_MODE`         | unset                                                | same override, read when `E2E_AUTH_MODE` is unset (shared with the backend/frontend env var) |
| `OIDC_ISSUER`       | `https://auth.127.0.0.1.nip.io/realms/aiops`         | token endpoint the `api` fixture and `hack/e2e-smoke.sh` use for the automation token |
| `AUTOMATION_CLIENT_ID` | `aiops-automation`                                | client-credentials client id (see "Authentication") |
| `AUTOMATION_CLIENT_SECRET` | `dev-automation-secret`                      | client-credentials secret; a literal dev value, never a real secret |
| `E2E_LANGFLOW_URL`  | `https://langflow.127.0.0.1.nip.io`                  | the iframe `src` `auth-login.spec.ts` expects on `/develop` (the frontend's `NEXT_PUBLIC_LANGFLOW_URL`) |

The managed backend of the fast tier also runs with `AIOPS_CHAT_MOCK=true`
(honoured by `backend/api/chat.py` only together with `TEST_MODE=true`):
`POST /v1alpha1/chat/completions` then streams `You said: <last user message>` without any instance,
so `chat.spec.ts` exercises the real `/api/chat` route handler and the AI SDK stream with only the instance list stubbed.

`playwright.config.ts` picks the effective auth mode per project:
`E2E_AUTH_MODE` if set, else `AUTH_MODE` if it names `oidc` or `disabled`,
else the project's own default — `disabled` for `fast`, `oidc` for `cluster`.
The fast tier's managed servers hardcode `AUTH_MODE=disabled` regardless of the shell environment, so it is never affected.

## Layout

```
frontend/
  playwright.config.ts      projects (fast, setup, cluster), web servers, reporters
  playwright/.auth/         saved logins (git-ignored; see "Authentication")
  e2e/
    fixtures.ts             `test` with the console guard, the `api` fixture, `asUser`, `userApi`, helm/kubectl helpers, `fixme()`
    auth.setup.ts            logs alice, bob and admin into Keycloak; the `setup` project
    pages/                  page objects; one class per screen, accessible-name locators only
      app-shell.ts          header, theme menu, heading, toasts, delete confirmation
      home.ts  model-catalog.ts  model-details.ts  finetune-form.ts  launch-model.ts
      vector-db-catalog.ts  vector-db-endpoints.ts  notebook-form.ts  notebooks.ts
      login.ts              the app's /login page and Keycloak's login form
      develop.ts            the Langflow iframe on /develop
    fast/                   one spec per scenario, hermetic
    cluster/                one spec per lifecycle, tagged @cluster
```

### Fixtures

- `test` from `e2e/fixtures.ts` extends Playwright's `test`.
  An auto fixture records every `console.error` and uncaught page error and fails the test at the end if any is left.
  Dev-only noise (React DevTools hint, Fast Refresh, favicon) is on the default allowlist.
  A test that expects a failed API call opts in with
  `test.use({ allowedConsoleErrors: [FAILED_RESOURCE] })` in a `describe` block.
  Keep that override to one pattern (combine several with `|`):
  Playwright reads an array whose second element is an object — a RegExp included — as a `[value, options]` fixture tuple
  and silently keeps only the first entry.
- `api` is a `BackendApi` bound to `E2E_BACKEND_URL`.
  It lists and deletes notebooks, vector DB instances, inference instances and fine-tune jobs,
  creates inference instances, lists chat targets, asks for embeddings,
  and polls with `waitForNotebookStatus`, `waitForVectorDBReady` and `waitForInferenceReady`.
  TEI embedding and reranker instances cannot run on an arm64 kind node (the TEI CPU image is amd64 only),
  so their LiteLLM routes are unit-tested here and proven on the lab.
  On the cluster project it attaches a bearer token (see "Authentication") and retries once, with a fresh token, on a 401 —
  the access token is short-lived and a poll can outlive it.
- `asUser(name)` returns a `BrowserContext` signed in as `"alice" | "bob" | "admin"`, restored from the saved storage state.
  Contexts are cached per test and closed in teardown.
  Every cluster spec is alice by default (the project's `storageState`); reach for `asUser` only for a second identity in the same test.
- `userApi(name)` is a `BackendApi` over the `asUser(name)` context's `request`,
  calling `/api/v1alpha1` through the UI proxy so the backend sees that user's own bearer token (`src/proxy.ts` adds it).
  The automation user behind `api` is a plain member:
  it cannot see alice's notebooks (owner or org admin only) and cannot delete what she created.
  Notebook specs therefore look up and poll through `userApi("alice")`,
  assert what another user may not read with `(await userApi("bob")).get("/notebooks/<id>")`,
  and clean up with `userApi("admin")`.
  Vector database instances stay readable org-wide, so `api` still serves those reads.
- `helmReleases()`, `waitForHelmReleaseGone()` and `kubernetesJobs()` shell out to `helm` and `kubectl` for the cluster tier.
- `fixme(reason)` skips a test for a known product bug and records the reason in the report.
  `E2E_RUN_FIXME=1` runs those tests so you can see when a fix has landed; remove the call once the test passes.
- `shortId()` gives a suffix for resource names (`e2e-jupyter-k3x9pq`).

### Authentication

The `setup` project (`e2e/auth.setup.ts`) opens `/login`, clicks "Sign in with Keycloak",
fills the Keycloak form (`#username`, `#password`, `#kc-login`) for alice, bob and admin,
and saves each session's `storageState` to `playwright/.auth/<user>.json`.
The `cluster` project declares `dependencies: ["setup"]`, so Playwright runs it first automatically;
the fast tier never runs it (`AUTH_MODE=disabled`, no Keycloak).
`playwright/.auth/` is git-ignored — each machine (and each restart of Keycloak, see below) regenerates it.

To run a spec as bob instead of alice, use the `asUser("bob")` fixture inside the test rather than changing the project's storage state:
alice creates a notebook with the default (alice) context, then `asUser("bob")` opens a second context to confirm bob gets 403 on it.
`notebook-access.spec.ts` is the worked example:

```ts
const bobPage = await (await asUser("bob")).newPage();
const response = await bobPage.goto(notebook.endpoint!);   // the gateway host
expect(response.status()).toBe(403);
const bob = await userApi("bob");
expect((await bob.get(`/notebooks/${notebook.id}`)).status()).toBe(403);
```

A whole spec can also start without any session:
`auth-login.spec.ts` sets `test.use({ storageState: { cookies: [], origins: [] } })`
and walks through the Keycloak form itself with the `KeycloakLoginPage` page object.

The saved storage states hold the Keycloak SSO cookie for `auth.127.0.0.1.nip.io` as well as the Auth.js cookie for the app,
so when a test opens a workload through the gateway,
the OIDC redirect normally comes straight back without showing the form;
`KeycloakLoginPage.signInIfShown` covers the case where it does not.

### Gateway hosts

Deployed instances are reached through the gateway, never through a port-forward.
The backend stores the gateway URL as the instance's `endpoint` (and `api_endpoint` for vector databases);
the cluster specs read it from the API and open it in the browser, or call it with Playwright's `request`.
The hostnames (`nb-<id8>`, `vdb-<id8>`, `vdb-<id8>-api`, `inf-<id8>` under `127.0.0.1.nip.io`,
where `<id8>` is the last eight hex characters of the instance id)
and the policy on each are documented in `docs/local-dev.md`,
"How deployed instances become reachable" and "Workload access".
The browser hosts need the Keycloak login (cookies on `127.0.0.1.nip.io`) and then pass ext-authz:
a notebook admits its owner or an org admin, a vector database any member.
The `-api` hosts want the instance key in the `api-key` (or `x-api-key`) header and answer 401 without it.
TLS on every host is signed by the local CA (`infra/local/ca/ca.crt`),
which is why the `cluster` and `setup` projects and the `api` fixture run with `ignoreHTTPSErrors`.

The backend also accepts one non-interactive identity: the `aiops-automation` client-credentials client.
`hack/e2e-smoke.sh` and the `api` fixture both use it —
neither can click through a Keycloak login, and the smoke test in particular runs against a bare backend with no browser at all.
Both obtain a token from `${OIDC_ISSUER}/protocol/openid-connect/token` with `grant_type=client_credentials`
and the `AUTOMATION_CLIENT_ID` / `AUTOMATION_CLIENT_SECRET` pair (defaults `aiops-automation` / `dev-automation-secret`, a dev-only secret),
cache it, send it as `Authorization: Bearer`, and fetch a fresh one after a 401.
The backend maps that token to a service user with the member role, not an owner or admin,
so it can read anything in the org but can only delete resources it created itself —
cluster specs delete through the UI as the owning user and only fall back to `api.delete*` for cleanup on a failed test.

Every saved `playwright/.auth/*.json` session and every automation token depends on the live Keycloak (`make auth-up`) staying up.
A Keycloak restart drops its in-memory sessions,
so a saved refresh token stops working and Auth.js's next refresh fails with `RefreshAccessTokenError`,
sending that spec back to `/login`.
Re-run the cluster tier (its `setup` project regenerates the sessions) after restarting Keycloak.

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
| `launch-form.spec.ts`         | the three wizard steps, engine filtering, empty argument name blocks the submit, rejected deploy toast; an Ollama tag offers only Ollama and needs no host, a Hugging Face id never offers Ollama | pass | 4 s |
| `chat.spec.ts`                | the mock target from `AIOPS_CHAT_MOCK`, streamed answer, history survives a reload, clear; `?target=` preselects; empty state links to the catalog | pass | 3 s |
| `providers.spec.ts`           | add a provider with the two mock models, table and chat targets update, disable hides its models, remove one model, delete, set a budget (in-memory secret store) | pass | 4 s |
| `registry.spec.ts`            | import `Qwen/Qwen3-0.6B-GGUF` from the fixture as a draft, its Ollama `hf.co/...` option, publish, catalog and wizard show it, deprecate, delete; add manually; add an Ollama tag from the manifest fixture | pass | 5 s |
| `usage.spec.ts`               | the Usage page on the mock rows: totals, the per-target table, the per-user table, switching the period | pass | 2 s |
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
| `auth-login.spec.ts`          | fresh context: `/` redirects to `/login`, Keycloak login as alice, user menu shows name and email, `/develop` embeds Langflow from the gateway host, sign out lands on `/login` | 2 s |
| `notebook-access.spec.ts`     | alice creates a Jupyter notebook, opens its gateway URL and sees JupyterLab; bob gets 403 on the same URL, does not see it in `/notebooks` and gets 403 from the API; alice deletes it | 42 s |
| `vector-db-credential.spec.ts`| alice deploys Qdrant, "Show credential" shows the key once, the `-api` host answers 401 without the key and 200 with it, second click says "already revealed", delete from the UI | 41 s |
| `chat-lifecycle.spec.ts`      | launch `qwen3:0.6b` on Ollama from the wizard (no host), Ready with an `inf-` endpoint and listed as a LiteLLM chat target, "Chat" on the endpoint page, one streamed answer on `/chat`, delete, Helm release gone | 3 to 10 min (image and model pull on the first run) |
| `embeddings-lifecycle.spec.ts`| launch `all-minilm:33m` on Ollama through the API, Ready, listed as an embedding target, two 384-dimension vectors from `POST /v1alpha1/embeddings` through LiteLLM, delete | 2 to 5 min |
| `hosted-chat.spec.ts`         | opt-in with `E2E_OPENAI_API_KEY`: admin adds OpenAI with `gpt-4o-mini`, chats with the hosted target, spend increases, provider deleted; skipped without the key | 1 min |
| `registry-lifecycle.spec.ts`  | import `Qwen/Qwen3-0.6B-GGUF` from the live Hugging Face Hub, publish, launch on Ollama with the `hf.co/...` reference, chat once, delete the instance and the entry | 3 to 8 min |

The cluster times assume the images are already on the kind node.
The first pull of a notebook or Qdrant image adds minutes; the tests wait up to 6 minutes for a notebook and 5 for a vector DB.
`notebook-access.spec.ts` raises its own timeout to 15 minutes because one chain covers create, Running, the gateway checks and delete.

`notebook-access.spec.ts` checks the three places bob is kept out of alice's notebook:
the gateway host (ext-authz, `backend/api/authz.py`), the `/notebooks` list and `GET /api/v1alpha1/notebooks/<id>`
(`owner_scope` and `authorize_owner` in `backend/auth/policy.py`; vector databases stay visible to the whole organization).
Its `afterEach` also asserts that no `e2e-nb-*` Helm release is left.

### Why the fine-tune create is stubbed in the fast tier

The TEST_MODE backend still submits a Kubernetes Job on `POST /models/{id}/finetune`.
Without a cluster it answers 500, and the fast tier asserts that toast.
The list, params, delete and logs interactions therefore run against `page.route` stubs that mirror the real response shapes; the cluster tier runs the real call.
