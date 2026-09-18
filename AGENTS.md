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
| `infra/` | Bare-metal lab setup and install notes, imported as is; `infra/local/` holds the kind, gateway, Keycloak, Langflow, LiteLLM, monitoring and compose config; `infra/lab/` the manifests, values and install order for the lab's k3s GPU node |
| `hack/` | `e2e-smoke.sh`, the API-level smoke test against the local stack |
| `docs/` | `local-dev.md`, `testing.md`, migration commit maps |

## How the pieces fit

1. The browser calls relative `/api/v1alpha1/*` paths. `frontend/src/proxy.ts` rewrites them to the backend
   (`AIOPS_BACKEND_URL` at request time, else the build-time `NEXT_PUBLIC_AIOPS_BACKEND_URL`),
   and attaches `Authorization: Bearer <accessToken>` from the signed-in session, so no CORS and no separate token dance.
2. The backend routers under `backend/api/` persist catalog and instance rows (SQLite by default, Postgres via `DATABASE_URL`)
   and hand deploys to `backend/controller/`, which renders Helm values from `backend/templates/*.yaml.jinja`
   and installs charts with pyhelm3 (the `helm` binary must be on `PATH`).
3. The model catalog is a registry in the database (`backend/registry/`, `backend/api/registry.py`, page `/models/registry`):
   entries carry source, license, parameters, capabilities, status and serving options (engine plus reference),
   importers read Hugging Face, the Ollama registry and OpenRouter, and `make registry-export` writes the seed
   `backend/raw_data/models.yaml` that an empty database loads. The wizard launches an entry through one of its serving options.
4. Charts are pulled at runtime from the URLs in `backend/raw_data/engine_charts.csv` and `vectordb.csv`;
   most point at `https://infracloudio.github.io/charts`, which is why chart publishing keeps landing in the
   `infracloudio/charts` repository even though the chart sources live here.
5. An APScheduler job in `backend/core.py` polls every 5 s for instances without an endpoint and fills it from the
   Kubernetes Service (LoadBalancer ingress, else cluster IP), or from the gateway hostname when
   `AIOPS_PARENT_DOMAIN` is set (see point 8). The UI polls the API every 5 s while work is pending.
6. Notebooks are `kind: Notebook` custom resources, so the cluster needs the standalone Kubeflow notebook controller
   (`make kind-up` installs it). GPU engines are catalog-only on a laptop;
   Ollama (`backend/controller/ollama_controller.py`, `charts/ollama`, engine flag `cpu`) is the one engine that runs on kind.
   `AIOPS_CHARTS_DIR` (set by `make backend` to `charts/`) makes the controllers install a chart from the checkout
   when `charts/<chart_name>/Chart.yaml` exists, so a chart can be tried before it is published.
7. **Identity: Keycloak is the only identity provider.**
   The UI signs users in with Auth.js against the realm `aiops` (OIDC code flow with PKCE)
   and keeps the access token in its session;
   the backend validates that token on every `/v1alpha1/*` route except `/health`
   with PyJWT against the realm's JWKS (`OIDC_ISSUER`, audience `aiops-api`),
   and scopes every list, read and write by organization and owner.
   `AUTH_MODE=disabled` skips both checks
   and is only honoured with `TEST_MODE=true` (backend) or logged as a warning at startup (frontend);
   both default to `oidc`.
8. **Deployed workloads are protected at the gateway, and never see the caller's identity directly.**
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
   Langflow has a policy of its own with the same ext-authz check and runs on the forwarded token
   (`infra/local/langflow/langflow.yaml`, ADR 0002).
9. **Chat, embeddings and rerank go through the control plane and LiteLLM, never straight to a model.**
   Every deployed inference instance is registered in the LiteLLM proxy (`backend/utils/litellm.py`, namespace `litellm`,
   `make litellm-up`) as model `inst-<id8>` with its in-cluster Service URL and workload credential;
   each organization gets a LiteLLM team and one virtual key in a Secret.
   The `/chat` page uses the Vercel AI SDK against the UI's route handler `frontend/src/app/api/chat/route.ts`,
   which calls `POST /v1alpha1/chat/completions` (`backend/api/chat.py`) with the session's bearer token and `model: inst-<id8>`;
   the backend checks the read policy and forwards to LiteLLM with the organization's key
   (`GET /v1alpha1/chat/targets` lists what a user may talk to, deployed instances and hosted provider models alike;
   `POST /v1alpha1/embeddings` and `/rerank` follow the same rule).
   Hosted providers (`backend/api/providers.py`, page `/providers`) are per organization and admin-managed:
   the key lives in a Secret, the picked models are registered as `prov-<id8>/<model>`,
   and the organization's LiteLLM team carries the monthly budget.
   Without `LITELLM_URL` the chat endpoint falls back to the instance's `inf-<id8>` gateway host with the workload credential,
   and embeddings and rerank answer 503.
   Conversations live in the browser only, one per signed-in user and target.
   Every forwarded request carries the platform user as the OpenAI `user` field, so LiteLLM attributes spend and tokens per user;
   `GET /v1alpha1/organizations/current/usage` aggregates its spend logs for the Usage page (`/usage`),
   and `make monitoring-up` scrapes LiteLLM into Prometheus with a Grafana dashboard (`charts/infracloud-dashboards`, uid `aiops-litellm`)
   that the endpoint pages embed for Ollama instances through `var-target`.
   `AIOPS_CHAT_MOCK=true` (honoured only with `TEST_MODE=true`) serves one mock target, canned answers and canned usage rows for the Playwright fast tier.

## Local stack and commands

```bash
make prereqs                                                # colima/kind/helm/kubectl/uv/pnpm check
make kind-up gateway-up ca-export auth-up db-up langflow-up litellm-up monitoring-up  # cluster, gateway+CA, Keycloak, Postgres, Langflow, LiteLLM, Prometheus+Grafana
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

## Packaging

`charts/aiops-platform` (version 0.3.0) is the umbrella chart that installs the platform (`docs/install.md`):
the backend and frontend templates live in the chart,
Postgres, Keycloak and LiteLLM are conditional dependencies (`<name>.enabled`, `<name>.external.*`) with fixed names
(`aiops-postgresql`, `aiops-keycloak`, `aiops-litellm`) so the subchart values can reference each other literally,
and one Secret `aiops-platform-secrets` holds every credential (generated by a pre-install hook, or copied from `secrets.existingSecret`).
The hook also writes `aiops-gateway-oidc` (the gateway policy's client secret) and `aiops-litellm-env` (the LiteLLM salt).
The realm the bundled Keycloak imports is derived from the dev realm by `hack/derive-realm.py`; re-run it after editing `infra/local/auth/realm-aiops.json`.
`make chart-lint` (`hack/chart-lint.sh`) lints and renders the default, external, kind and lab values with assertions;
`make chart-images chart-smoke` installs on kind in namespace `aiops-platform` under `platform.127.0.0.1.nip.io`, reusing the dev Gateway,
and `hack/chart-smoke.sh` checks the API, the realm and the login page through the gateway.
The UI reads Grafana, Langflow and Jaeger URLs at runtime from `GET /v1alpha1/config/ui` (`backend/api/config.py`, backend env `GRAFANA_URL`, `LANGFLOW_URL`, `JAEGER_URL`),
falling back to the build-time `NEXT_PUBLIC_*` values (`frontend/src/lib/runtimeConfig.ts`).
`backend.hfCache.create` renders the `hf-cache` claim the GPU engine controllers mount by that fixed name (off by default).
The lab's GPU node is a single k3s node that also carries a dormant Platform9 PCD install, not the kubespray lab under `infra/kubernetes/`:
`infra/lab/README.md` has its measured facts, what it reuses (the node's cert-manager and MetalLB) and the install order,
`test/values-lab.yaml` is the chart fixture, and `hack/lab-dry-run.sh` checks all of it against the node without changing it.
Never run `make gateway-up` against that node; it would install a second cert-manager.
`charts-release.yml` lints the chart with every other chart, but only on push to `main`, not on pull requests;
`make chart-lint` is the pre-PR check.
Its Bitnami and LiteLLM dependencies are OCI references and need no `helm repo add`.

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
pull requests. The image workflows (`*-image.yml`) publish `ghcr.io/infracloudio/aiops-backend` and `aiops-frontend`
on every push to `main` that changes `backend/` or `frontend/`, tagged `main` and the seven-character commit SHA,
and build without pushing on pull requests.
Both workflows share one path list on purpose: the chart pins both images through the single `global.imageTag`,
so every application commit must publish the same tag for both
(`git log -1 --format=%H -- backend frontend | cut -c1-7` is the newest one; `make chart-images` builds the same tag for kind).

Chart publishing: the chart sources live here, but releases are published by the `infracloudio/charts` repository's
own chart-releaser workflow. To publish, sync `charts/<name>/` into that repository's `charts/<name>/` on a branch and
open a pull request there (see infracloudio/charts#25 for the pattern); merging releases the
bumped versions to `https://infracloudio.github.io/charts`, which the backend reads at runtime. The manual publish step
in `charts-release.yml` remains available with a `CHARTS_PUBLISH_TOKEN` secret but is not the normal path.
