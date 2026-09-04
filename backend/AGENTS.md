# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
`AGENTS.md` is the canonical file and `CLAUDE.md` is a symlink to it.
Read the repository root `AGENTS.md` first; this file covers only `backend/`.

## Commands

```bash
uv sync --group dev                       # install (Python 3.13, uv); helm must be on PATH
uv run uvicorn app:app --reload           # API on :8000, SQLite ./database.db unless DATABASE_URL is set
./hack/runtest.sh                         # all tests (sets TEST_MODE=true, wipes tmp/*.db)
./hack/runtest.sh -u                      # regenerate snapshots/ (only for intended output changes)
TEST_MODE=true uv run pytest test_app.py::test_create_notebook_rejects_duplicate_name -q   # one test
./hack/lint.sh                            # ruff check + ruff format --check
./hack/format.sh                          # ruff format
./hack/sort-imports.sh                    # ruff check --select I --fix
docker build -t aiops-backend .
```

Tests need `TEST_MODE=true`: `utils/genid.py` reads it at import to make ids deterministic for the snapshots,
`db/database.py` then uses a per-run SQLite file under `tmp/`, and `core.py` skips the scheduler.
The Helm client runs `helm version` when a controller is constructed, so tests need the binary as well.

## Architecture

- `app.py` calls `core.create_app()`, which registers the routers from `api/`, seeds the database
  (`db/db.py`, `init_db` → `load_initial_data` from `raw_data/*.csv`) and starts the APScheduler jobs in a
  FastAPI lifespan. `db/db.py` also does a home-grown schema sync (`update_table_definitions`, no Alembic).
- `api/*.py` are the routers (`/v1alpha1/...`): `models`, `engines`, `hosts`, `inference_instance`,
  `vectordb` and `vectordb_instance`, `notebooks`, `model_adapters`, `finetune`. Create endpoints persist a row,
  then call a controller; on install failure they delete the row again.
- `controller/`: `base_controller.Controller` is the Helm workflow (fetch chart, render values, install, upgrade,
  uninstall) subclassed per inference engine (`hf`, `vllm`, `nim`, `opea`); `vectordb_controller` and
  `notebooks_controller` are standalone but follow the same shape; `finetune_controller` submits Kubernetes Jobs.
  `base_controller.get_chart` strips informational `Chart.yaml` fields that pyhelm3's pydantic models reject
  (the Milvus chart), and the install/uninstall helpers skip release-status parsing for the same reason.
- `templates/*.yaml.jinja` render the Helm values; the context comes from the instance schema plus engine defaults
  (`raw_data/*default_args*.csv`), and the backend sends only user-changed args because the controllers merge the
  defaults. `snapshots/test_controller/*` are the rendered values the tests compare against.
- `models/` are SQLAlchemy models, `schemas/` the pydantic request and response models. Request-only validation
  lives in subclasses (for example `schemas/notebook.py` `NotebookCreateSchema`: DNS-1123 name, max 32 chars,
  because the chart cuts `<name>-<id>-kf-notebooks-<name>` at 41).
- `utils/kubernetes_utils.py` loads kube config (file, then in-cluster) and resolves service endpoints:
  LoadBalancer ingress IP or hostname, else the cluster IP, and `None` while nothing is known so the scheduler
  keeps polling. `paths.py` anchors `templates/`, `raw_data/` and `tmp/` on the package directory, so the app
  works from any working directory.

## Conventions and gotchas

- The default namespace is `ai-stack`, overridable with `AIOPS_NAMESPACE`; controllers read it at call time.
- Every `HTTPException` carries a human-readable string `detail`; the frontend shows it in a toast.
  Validation errors are 422, duplicates 409, an unreachable cluster 503.
- `pyproject.toml` turns `DeprecationWarning` into errors in tests; add a targeted `filterwarnings` entry rather
  than silencing them globally.
- Ruff line length is 79; `B008` (`Depends()` defaults) and `E501` are ignored on purpose.
- `chart_values/*.yaml` are reference values for humans and are not read by the code.
- Do not commit `config.yaml` manifests; copy `manifests/config.example.yaml` and fill the secrets locally.
