# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
`AGENTS.md` is the canonical file; `CLAUDE.md` is a symlink to it so other agent harnesses read the same guidance.
`backend/` and `frontend/` carry their own `AGENTS.md` with the details that only matter there.

## What this repository is

A control plane that onboards AI infrastructure and deploys AI services on Kubernetes through Helm:
inference engines (Ollama on CPU, Hugging Face TGI/TEI, vLLM, NVIDIA NIM, OPEA), vector databases (ChromaDB, Milvus, Qdrant),
Kubeflow notebooks, LoRA adapters and fine-tune jobs, plus a chat page that streams answers from a deployed model.
It is a monorepo assembled from four former repositories with their history (`MIGRATION.md`).

| Directory | Contents |
| --- | --- |
| `backend/` | FastAPI control plane (Python 3.13, uv, SQLAlchemy 2, pyhelm3) |
| `frontend/` | Next.js 16 UI (React 19, Tailwind 4, shadcn/ui, pnpm) plus the Playwright e2e suite |
| `charts/<name>/` | Helm charts published to <https://infracloudio.github.io/charts> |
| `infra/` | Bare-metal lab setup and install notes, imported as is; `infra/local/` holds the kind and compose config |
| `hack/` | `e2e-smoke.sh`, the API-level smoke test against the local stack |
| `docs/` | `local-dev.md`, `testing.md`, migration commit maps |

## How the pieces fit

1. The browser calls relative `/api/v1alpha1/*` paths. `frontend/src/proxy.ts` rewrites them to the backend
   (`AIOPS_BACKEND_URL` at request time, else the build-time `NEXT_PUBLIC_AIOPS_BACKEND_URL`),
   and attaches `Authorization: Bearer <accessToken>` from the signed-in session, so no CORS and no separate token dance.
2. The backend routers under `backend/api/` persist catalog and instance rows (SQLite by default, Postgres via `DATABASE_URL`)
   and hand deploys to `backend/controller/`, which renders Helm values from `backend/templates/*.yaml.jinja`
   and installs charts with pyhelm3 (the `helm` binary must be on `PATH`).
3. Charts are pulled at runtime from the URLs in `backend/raw_data/engine_charts.csv` and `vectordb.csv`;
   most point at `https://infracloudio.github.io/charts`, which is why chart publishing keeps landing in the
   `infracloudio/charts` repository even though the chart sources live here.
4. An APScheduler job in `backend/core.py` polls every 5 s for instances without an endpoint and fills it from the
   Kubernetes Service (LoadBalancer ingress, else cluster IP), or from the gateway hostname when
   `AIOPS_PARENT_DOMAIN` is set (see point 7). The UI polls the API every 5 s while work is pending.
5. Notebooks are `kind: Notebook` custom resources, so the cluster needs the standalone Kubeflow notebook controller
   (`make kind-up` installs it). GPU engines are catalog-only on a laptop;
   Ollama (`backend/controller/ollama_controller.py`, `charts/ollama`, engine flag `cpu`) is the one engine that runs on kind.
   `AIOPS_CHARTS_DIR` (set by `make backend` to `charts/`) makes the controllers install a chart from the checkout
   when `charts/<chart_name>/Chart.yaml` exists, so a chart can be tried before it is published.
6. **Identity: Keycloak is the only identity provider.**
   The UI signs users in with Auth.js against the realm `aiops` (OIDC code flow with PKCE)
   and keeps the access token in its session;
   the backend validates that token on every `/v1alpha1/*` route except `/health`
   with PyJWT against the realm's JWKS (`OIDC_ISSUER`, audience `aiops-api`),
   and scopes every list, read and write by organization and owner.
   `AUTH_MODE=disabled` skips both checks
   and is only honoured with `TEST_MODE=true` (backend) or logged as a warning at startup (frontend);
   both default to `oidc`.
7. **Deployed workloads are protected at the gateway, and never see the caller's identity directly.**
   Each instance's controller creates one or two `HTTPRoute`s under a deterministic hostname
   (`nb-<id8>`, `vdb-<id8>`, `vdb-<id8>-api`, `inf-<id8>.<parent domain>`,
   where `<id8>` is the *last* eight hex characters of the instance id)
   and joins the browser routes to one shared Envoy Gateway `SecurityPolicy`, `aiops-workloads-oidc`:
   it logs the browser in against Keycloak,
   then calls the backend's `GET /v1alpha1/authz/route` (ext-authz)
   to ask whether this user may open this host.
   SDK-facing routes (`-api` and `inf-` hosts) instead get a per-instance `apiKeyAuth` `SecurityPolicy`
   reading the workload credential the backend generated and stored (`backend/utils/credentials.py`);
   both kinds of policy, plus the `HTTPRoute`s themselves, are created by `backend/utils/gateway.py`
   and are no-ops without `AIOPS_PARENT_DOMAIN` set,
   so a plain `uv run uvicorn` behaves exactly as before the gateway existed.
8. **Chat goes through the control plane, never straight to a model.**
   The `/chat` page uses the Vercel AI SDK against the UI's own route handler `frontend/src/app/api/chat/route.ts`,
   which calls `POST /v1alpha1/chat/completions` (`backend/api/chat.py`) with the session's bearer token
   and the target instance in `X-AIOps-Instance`;
   the backend checks the read policy, then forwards the OpenAI-compatible body to the instance's `inf-<id8>` gateway host
   with the instance's workload credential and streams the SSE answer back.
   Conversations live in the browser only.
   `AIOPS_CHAT_MOCK=true` (honoured only with `TEST_MODE=true`) answers with a canned echo for the Playwright fast tier.

## Local stack and commands

```bash
make prereqs                                                # colima/kind/helm/kubectl/uv/pnpm check
make kind-up gateway-up ca-export auth-up db-up langflow-up  # cluster, gateway+CA, Keycloak, Postgres, Langflow
make backend                                                 # uvicorn on :8000 (needs helm and a kubeconfig)
make frontend                                                # next dev on :3000 (login goes through Keycloak)
make e2e-smoke                                               # API smoke: Qdrant + Jupyter notebook create/ready/delete
make ui-e2e                                                  # Playwright fast tier, no cluster (TEST_MODE backend on :8001, built UI on :3001)
make ui-e2e-cluster                                          # Playwright cluster tier against :3000/:8000, logged in as alice
```

`AUTH_MODE` (`oidc` by default, `disabled` for the fast Playwright tier and single backend tests)
is the one switch that turns authentication on or off end to end;
see `docs/local-dev.md` for every target above, the dev users and clients,
and how deployed instances become reachable and protected.
`make gateway-up` and `make auth-up` also need the local CA trusted or exported to an env var
(`make trust-ca`, `SSL_CERT_FILE`/`NODE_EXTRA_CA_CERTS`/`REQUESTS_CA_BUNDLE` pointed at `infra/local/ca/ca.crt`)
before curl, Node or Python tooling will accept the gateway's TLS certificate.
`docs/local-dev.md` also covers resets (`colima delete --data`), the inotify limit colima needs,
and why deployed instances no longer need a `LoadBalancer` IP.
`docs/testing.md` explains both e2e tiers and how to add a scenario.

## Conventions that are not obvious from the code

- Backend: `uv` for everything, `ruff` for lint and format (`backend/hack/*.sh`); `TEST_MODE=true` gives a per-run
  SQLite file, deterministic ids and no scheduler. Snapshot files under `backend/snapshots/` are golden output;
  regenerate with `./hack/runtest.sh -u` only when the change is intended.
  Schema changes are Alembic migrations (`backend/alembic/versions/`), never edits to the baseline or `create_all`;
  `make db-migrate` applies them locally.
- Frontend: `pnpm` only (`packageManager` is pinned); `next dev` writes a managed block into `frontend/AGENTS.md`,
  keep it committed. Playwright fixtures fail a test on any console error.
- Charts: umbrella charts (`ai-stack`, `guardrails-usvc`) use `file://../<chart>` dependencies; bump the chart
  `version` whenever templates or `appVersion` change.
- Kubernetes secrets live in a git-ignored `config.yaml` created from `backend/manifests/config.example.yaml`
  or `infra/aiops/backend/config.example.yaml`. Real tokens were purged from history once; do not add any.
- `AUTH_MODE=disabled` is a real security bypass, not a convenience flag:
  the backend refuses it outright unless `TEST_MODE=true` is also set,
  and it must never be set that way anywhere the real stack runs.
- Do not commit `infra/local/ca/` (the generated local CA)
  or `frontend/playwright/.auth/` (saved Keycloak login state for the Playwright cluster tier);
  both are git-ignored on purpose.
- Markdown in this repository uses semantic line breaks (one sentence or clause per line).

## CI

Workflows in `.github/workflows/` are path-filtered: `backend-ci.yml`, `frontend-ci.yml` and `charts-release.yml`
(lint and package only on push) run on `main` and pull requests; `frontend-e2e.yml` runs the fast Playwright tier on
pull requests. Image builds (`*-image.yml`) are `workflow_dispatch` only, because the `:main` image tags are pulled by
the lab manifests.

Chart publishing: the chart sources live here, but releases are published by the `infracloudio/charts` repository's
own chart-releaser workflow. To publish, sync `charts/<name>/` into that repository's `charts/<name>/` on a branch and
open a pull request there (see infracloudio/charts#25 for the pattern); merging releases the
bumped versions to `https://infracloudio.github.io/charts`, which the backend reads at runtime. The manual publish step
in `charts-release.yml` remains available with a `CHARTS_PUBLISH_TOKEN` secret but is not the normal path.
