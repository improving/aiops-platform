# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
`AGENTS.md` is the canonical file; `CLAUDE.md` is a symlink to it so other agent harnesses read the same guidance.
`backend/` and `frontend/` carry their own `AGENTS.md` with the details that only matter there.

## What this repository is

A control plane that onboards AI infrastructure and deploys AI services on Kubernetes through Helm:
inference engines (Hugging Face TGI/TEI, vLLM, NVIDIA NIM, OPEA), vector databases (ChromaDB, Milvus, Qdrant),
Kubeflow notebooks, LoRA adapters and fine-tune jobs.
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
   (`AIOPS_BACKEND_URL` at request time, else the build-time `NEXT_PUBLIC_AIOPS_BACKEND_URL`), so no CORS.
2. The backend routers under `backend/api/` persist catalog and instance rows (SQLite by default, Postgres via `DATABASE_URL`)
   and hand deploys to `backend/controller/`, which renders Helm values from `backend/templates/*.yaml.jinja`
   and installs charts with pyhelm3 (the `helm` binary must be on `PATH`).
3. Charts are pulled at runtime from the URLs in `backend/raw_data/engine_charts.csv` and `vectordb.csv`;
   most point at `https://infracloudio.github.io/charts`, which is why chart publishing keeps landing in the
   `infracloudio/charts` repository even though the chart sources live here.
4. An APScheduler job in `backend/core.py` polls every 5 s for instances without an endpoint and fills it from the
   Kubernetes Service (LoadBalancer ingress, else cluster IP). The UI polls the API every 5 s while work is pending.
5. Notebooks are `kind: Notebook` custom resources, so the cluster needs the standalone Kubeflow notebook controller
   (`make kind-up` installs it). GPU engines are catalog-only on a laptop.

## Local stack and commands

```bash
make prereqs           # colima/kind/helm/kubectl/uv/pnpm check
make kind-up db-up     # kind cluster "aiops" + notebook controller + Postgres
make langflow-up       # optional Langflow for the Develop page
make backend           # uvicorn on :8000 (needs helm and a kubeconfig)
make frontend          # next dev on :3000
make e2e-smoke         # API smoke: Qdrant + Jupyter notebook create/ready/delete
make ui-e2e            # Playwright fast tier, no cluster (TEST_MODE backend on :8001, built UI on :3001)
make ui-e2e-cluster    # Playwright cluster tier against :3000/:8000
```

`docs/local-dev.md` covers resets (`colima delete --data`), the inotify limit colima needs, and why LoadBalancer
services stay pending locally. `docs/testing.md` explains both e2e tiers and how to add a scenario.

## Conventions that are not obvious from the code

- Backend: `uv` for everything, `ruff` for lint and format (`backend/hack/*.sh`); `TEST_MODE=true` gives a per-run
  SQLite file, deterministic ids and no scheduler. Snapshot files under `backend/snapshots/` are golden output;
  regenerate with `./hack/runtest.sh -u` only when the change is intended.
- Frontend: `pnpm` only (`packageManager` is pinned); `next dev` writes a managed block into `frontend/AGENTS.md`,
  keep it committed. Playwright fixtures fail a test on any console error.
- Charts: umbrella charts (`ai-stack`, `guardrails-usvc`) use `file://../<chart>` dependencies; bump the chart
  `version` whenever templates or `appVersion` change.
- Kubernetes secrets live in a git-ignored `config.yaml` created from `backend/manifests/config.example.yaml`
  or `infra/aiops/backend/config.example.yaml`. Real tokens were purged from history once; do not add any.
- Markdown in this repository uses semantic line breaks (one sentence or clause per line).

## CI

Workflows in `.github/workflows/` are path-filtered: `backend-ci.yml`, `frontend-ci.yml` and `charts-release.yml`
(lint and package only on push) run on `main` and pull requests; `frontend-e2e.yml` runs the fast Playwright tier on
pull requests. Image builds (`*-image.yml`) and the chart publish step are `workflow_dispatch` only, because the
`:main` image tags are pulled by the lab manifests and publishing writes to the public charts repository.
