# aiops-backend

FastAPI control plane that deploys AI services on Kubernetes with Helm.
Values files are rendered from the Jinja templates in `templates/`.

## Requirements

- Python 3.13 and [uv](https://docs.astral.sh/uv/).
- The `helm` binary on `PATH`;
  the Helm client is created at controller construction time, so the tests need it too.
- A kubeconfig or in-cluster credentials for the deploy endpoints.

## Install

```bash
uv sync --group dev
```

## Run

```bash
uv run uvicorn app:app --reload
```

The API listens on `http://127.0.0.1:8000`;
`GET /health` returns `{"message": "OK"}`.

## Environment variables

| Variable            | Default                  | Purpose                                                      |
| ------------------- | ------------------------ | ------------------------------------------------------------ |
| `DATABASE_URL`      | `sqlite:///./database.db` | `sqlite://...` or `postgresql://host[:port]`.               |
| `DATABASE_NAME`     | `postgres`               | Postgres database name.                                      |
| `DATABASE_USER`     | `postgres`               | Postgres user.                                               |
| `DATABASE_PASSWORD` | `postgres`               | Postgres password.                                           |
| `TEST_MODE`         | `false`                  | Per-test SQLite under `tmp/`, deterministic ids, no scheduler. |
| `HF_API_TOKEN`      | unset                    | Hugging Face token passed to inference and finetune jobs.    |
| `NGC_API_KEY`       | unset                    | NVIDIA NGC key for NIM charts.                               |
| `AIOPS_NAMESPACE`   | `ai-stack`               | Namespace for managed Helm releases and jobs.                |
| `KUBECONFIG`        | unset                    | Kubeconfig path; falls back to in-cluster config.            |

## Tests and lint

```bash
./hack/runtest.sh          # uv run pytest, TEST_MODE=true
./hack/runtest.sh -u       # regenerate the snapshots in snapshots/
./hack/lint.sh             # ruff check + ruff format --check
./hack/format.sh           # ruff format
./hack/sort-imports.sh     # ruff check --select I --fix
```

Snapshot files under `snapshots/` are golden files;
regenerate them only when a change in output is intended.

## Container image

```bash
docker build -t aiops-backend .
```

The image is based on `python:3.13-slim`, installs dependencies with `uv sync --frozen`,
downloads Helm for the target architecture, and runs as a non-root user.
