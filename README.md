# AIOps Platform

A control plane that onboards AI infrastructure and deploys AI services on Kubernetes through Helm:
inference engines (Hugging Face TGI and TEI, vLLM, NVIDIA NIM, OPEA),
vector databases (ChromaDB, Milvus, Qdrant),
Kubeflow notebooks, LoRA adapters and fine-tune jobs.

This monorepo combines four former repositories with their full commit history.
See `MIGRATION.md` for the mapping and for what was removed from history.

| Directory | Contents |
|---|---|
| `backend/` | FastAPI control plane API (Python 3.13, uv, SQLAlchemy 2, pyhelm3) |
| `frontend/` | Next.js 16 web UI (React 19, Tailwind 4, shadcn, pnpm) |
| `charts/` | Helm charts published to <https://infracloudio.github.io/charts> |
| `infra/` | Bare-metal lab setup, cluster bring-up and platform install notes |
| `infra/local/` | kind cluster and Postgres config for local development |
| `hack/` | Repository-level scripts, including the end-to-end smoke test |
| `docs/` | Local development guide and migration commit maps |

## Quick start (local, no GPU)

Prerequisites: colima (or another Docker daemon), kind, Helm, kubectl, uv, pnpm.
`make prereqs` reports what is missing.

```bash
colima start --cpu 4 --memory 8
make kind-up        # kind cluster "aiops", Kubeflow notebook controller, namespace ai-stack
make db-up          # Postgres in docker compose on localhost:5432
make backend        # terminal 1: API on http://localhost:8000
make frontend       # terminal 2: UI on http://localhost:3000
make e2e-smoke      # terminal 3: creates a Qdrant instance and a Jupyter notebook, then deletes them
```

The UI proxies `/api/v1alpha1/*` to the backend, so no CORS setup is needed.
GPU inference engines stay catalog-only on a laptop;
vector databases and notebooks deploy for real into the kind cluster.
`docs/local-dev.md` has the full walkthrough and troubleshooting.

## Development

- Backend: `cd backend && uv sync && uv run pytest`, lint with `./hack/lint.sh`, format with `./hack/format.sh`.
- Frontend: `cd frontend && pnpm install && pnpm lint && pnpm build`.
- Charts: `helm lint --strict charts/<name>` and `helm template x charts/<name>`.

CI runs per directory on pull requests (`.github/workflows/`).
Container images are pushed to `ghcr.io/infracloudio/aiops-backend` and `ghcr.io/infracloudio/aiops-frontend`.
Chart releases are published into the `infracloudio/charts` repository so the chart URL above stays stable.

## Configuration

The backend reads `DATABASE_URL`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`,
`AIOPS_NAMESPACE`, `HF_API_TOKEN`, `NGC_API_KEY` and the usual `KUBECONFIG`.
Kubernetes manifests take secrets from a `config.yaml` created from `backend/manifests/config.example.yaml`;
that file is git-ignored.
