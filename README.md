# AIOps Platform

A control plane that onboards AI infrastructure and deploys AI services on Kubernetes through Helm:
inference engines (HF TGI/TEI, vLLM, NVIDIA NIM, OPEA), vector databases (ChromaDB, Milvus, Qdrant),
Kubeflow notebooks, LoRA adapters and fine-tune jobs.

This monorepo combines four former repositories with their full commit history.
See `MIGRATION.md` for the mapping.

| Directory | Contents |
|---|---|
| `backend/` | FastAPI control plane API |
| `frontend/` | Next.js web UI |
| `charts/` | Helm charts published to <https://infracloudio.github.io/charts> |
| `infra/` | Bare-metal lab setup, cluster bring-up and platform install notes |
