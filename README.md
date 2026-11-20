# AIOps Platform

A control plane that onboards AI infrastructure and deploys AI services on Kubernetes through Helm:
inference engines (Hugging Face TGI and TEI, vLLM, NVIDIA NIM, OPEA),
vector databases (ChromaDB, Milvus, Qdrant),
Kubeflow notebooks, LoRA adapters and fine-tune jobs.

| Directory | Contents |
|---|---|
| `backend/` | FastAPI control plane API (Python 3.13, uv, SQLAlchemy 2, pyhelm3) |
| `frontend/` | Next.js 16 web UI (React 19, Tailwind 4, shadcn, pnpm) |
| `charts/` | Helm charts published to <https://infracloudio.github.io/charts> |
| `infra/local/` | kind cluster, gateway, Keycloak, Langflow, LiteLLM and Postgres config for local development |
| `hack/` | Repository-level scripts, including the end-to-end smoke test |
| `docs/` | Local development guide, install guide, API reference, ADRs and design notes |

## Quick start (local, no GPU)

Prerequisites: colima (or another Docker daemon), kind, Helm, kubectl, uv, pnpm.
`make prereqs` reports what is missing.

```bash
colima start --cpu 4 --memory 8
make kind-up gateway-up ca-export auth-up db-up langflow-up
# kind cluster "aiops"; Envoy Gateway + cert-manager + the local CA;
# Keycloak with the dev realm; Postgres; Langflow -- all behind the gateway
make backend        # terminal 1: API on http://localhost:8000
make frontend       # terminal 2: UI on http://localhost:3000
make e2e-smoke      # terminal 3: creates a Qdrant instance and a Jupyter notebook, then deletes them
```

The UI proxies `/api/v1alpha1/*` to the backend, so no CORS setup is needed,
and signs users in through Keycloak before any page loads
(dev users `alice`/`alice`, `bob`/`bob`, `admin`/`admin`, same password as username).
curl, Node and Python tooling need to trust the gateway's local CA before they can reach
`https://*.127.0.0.1.nip.io` -- run `make trust-ca` for the command it prints
(`sudo`, macOS Keychain, not run automatically),
or export `SSL_CERT_FILE`/`NODE_EXTRA_CA_CERTS` to `infra/local/ca/ca.crt` for one shell.
GPU inference engines stay catalog-only on a laptop;
vector databases and notebooks deploy for real into the kind cluster,
each behind its own gateway hostname and identity check.
`docs/local-dev.md` has the full walkthrough and troubleshooting.

## Development

- Backend: `cd backend && uv sync && uv run pytest`, lint with `./hack/lint.sh`, format with `./hack/format.sh`.
- Frontend: `cd frontend && pnpm install && pnpm lint && pnpm build`.
- Charts: `helm lint --strict charts/<name>` and `helm template x charts/<name>`.

CI runs per directory on pull requests (`.github/workflows/`).
Container images are pushed to `ghcr.io/infracloudio/aiops-backend` and `ghcr.io/infracloudio/aiops-frontend`
on every push to `main` that changes `backend/` or `frontend/`, tagged `main` and the seven-character commit SHA.
Chart releases are published into the `infracloudio/charts` repository so the chart URL above stays stable.

## Configuration

The backend reads `DATABASE_URL`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD`,
`AIOPS_NAMESPACE`, `HF_API_TOKEN`, `NGC_API_KEY`, `AUTH_MODE`/`OIDC_ISSUER` and the usual `KUBECONFIG`.
Kubernetes manifests take secrets from a `config.yaml` created from `backend/manifests/config.example.yaml`;
that file is git-ignored.
