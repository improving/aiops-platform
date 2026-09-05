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
`conftest.py` defaults `TEST_MODE=true` and `AUTH_MODE=disabled`, so single-test commands work without them.
The SQLite file name is deterministic too: a direct `pytest` run reuses the file of the previous run,
so remove `tmp/*.db` (as `runtest.sh` does) when a run fails on a duplicate id.
The Helm client runs `helm version` when a controller is constructed, so tests need the binary as well.

## Architecture

- `app.py` calls `core.create_app()`, which registers the routers from `api/`, seeds the database
  (`db/db.py`, `init_db` → `load_initial_data` from `raw_data/*.csv`) and starts the APScheduler jobs in a
  FastAPI lifespan. `init_db` first runs the Alembic migrations (`db/migrate.py` `upgrade_to_head`,
  `alembic/versions/`) on the app engine; a database that predates Alembic is stamped `0001` first.
- `api/*.py` are the routers (`/v1alpha1/...`): `models`, `engines`, `hosts`, `inference_instance`,
  `vectordb` and `vectordb_instance`, `notebooks`, `model_adapters`, `finetune`, `credentials`, `authz`, `chat`.
  Create endpoints persist a row, then call a controller; on install failure they delete the row again.
  `inference_instance` requires `HF_API_TOKEN` for every engine except those in `NO_HF_TOKEN_ENGINES` (Ollama).
- `controller/`: `base_controller.Controller` is the Helm workflow (fetch chart, render values, install, upgrade,
  uninstall) subclassed per inference engine (`hf`, `vllm`, `nim`, `opea`, `ollama`); `vectordb_controller` and
  `notebooks_controller` are standalone but follow the same shape; `finetune_controller` submits Kubernetes Jobs.
  `local_chart_path(chart_name)` honours `AIOPS_CHARTS_DIR`: when `<dir>/<chart_name>/Chart.yaml` exists the
  chart is installed from that directory instead of `chart_repo` (the vector DB and notebook controllers do not
  read it yet).
  `OllamaController.get_service_name` returns the bare release name, because the chart's standard fullname helper
  drops the chart suffix when the release (`ollama-<id8>`) already contains it; the template only renders
  `models.pull`, `service`, `resources`, `env` and `nodeSelector` (no GPU resources).
  Engines carry a `cpu` flag (`raw_data/engines.csv`, migration `0004`) that the launch wizard uses to make the
  accelerator step optional.
  `base_controller.get_chart` strips informational `Chart.yaml` fields that pyhelm3's pydantic models reject
  (the Milvus chart), and the install/uninstall helpers skip release-status parsing for the same reason.
- `templates/*.yaml.jinja` render the Helm values; the context comes from the instance schema plus engine defaults
  (`raw_data/*default_args*.csv`), and the backend sends only user-changed args because the controllers merge the
  defaults. `snapshots/test_controller/*` are the rendered values the tests compare against.
- `models/` are SQLAlchemy models, `schemas/` the pydantic request and response models. Request-only validation
  lives in subclasses (for example `schemas/notebook.py` `NotebookCreateSchema`: DNS-1123 name, max 32 chars,
  because the chart cuts `<name>-<id>-kf-notebooks-<name>` at 41).
- `utils/gateway.py` creates and deletes the `HTTPRoute`s and gateway `SecurityPolicy`/`BackendTrafficPolicy`
  objects for every deployed instance:
  browser hosts (`nb-<id8>`, `vdb-<id8>`) join the shared `add_oidc_target`/`remove_oidc_target` policy
  `aiops-workloads-oidc`, SDK hosts (`vdb-<id8>-api`, `inf-<id8>`) get their own `apikey` policy once a
  credential Secret exists, notebook routes also get a `BackendTrafficPolicy` for long-lived WebSockets,
  and `ensure_reference_grant`/`ensure_gateway_client_secret` extend the cross-namespace `ReferenceGrant`s
  and copy the OIDC client Secret when `AIOPS_NAMESPACE` points somewhere other than `ai-stack`.
  Every function is a no-op without `AIOPS_PARENT_DOMAIN`.
- `utils/kubernetes_utils.py` resolves the fallback service endpoint used when the gateway is not configured
  (loads kube config, file then in-cluster; LoadBalancer ingress IP or hostname, else the cluster IP,
  and `None` while nothing is known so the scheduler keeps polling).
  `paths.py` anchors `templates/`, `raw_data/` and `tmp/` on the package directory,
  so the app works from any working directory.

## Authentication

- `auth/settings.py` reads `AUTH_MODE` (`oidc` default, or `disabled`), `OIDC_ISSUER`, `OIDC_AUDIENCE`
  (`aiops-api`) and `OIDC_JWKS_URL` (default `<issuer>/protocol/openid-connect/certs`) at call time.
  `create_app` fails at startup on `AUTH_MODE=disabled` without `TEST_MODE=true` and on `oidc` without an issuer;
  the JWKS client (`auth/jwt.py`, `PyJWKClient(cache_keys=True)`) is built on the first request, so an unreachable
  Keycloak does not block startup.
  The fetch uses `urllib`: put a private CA in `SSL_CERT_FILE`.
- `auth/current_user.py` `get_current_user` is the dependency on every route except `/health`
  (`HTTPBearer(auto_error=False)`, 401s carry `WWW-Authenticate: Bearer`, an unreachable JWKS is a 503).
  It upserts `users` by `sub` and the membership in the `default` organization with the role from
  `realm_access.roles` (`admin` > `member` > `viewer`; Keycloak owns the role, so a changed role is written back).
  Client-credentials tokens (no `email`, `azp` set) become `svc:<azp>` with role `member`.
  In `disabled` mode every request is the `dev` admin. `require_role(...)` wraps it
  (`require_writer` on create routes, `require_admin` on `/reload-data` and `/refresh-db`).
- `auth/policy.py`: list routes filter with `org_scope(model, user)`, create routes set `org_id`/`owner_id`,
  get/update/delete call `authorize_read`/`authorize_write` (403 `You do not own this <kind>`).
  `Policy.can_read` is same organization (rows with `org_id` NULL belong to `default`),
  `Policy.can_write` is the owner or an org admin (rows with `owner_id` NULL are admin-only).
  Catalogs (`models`, `engines`, `vectordb`) are global; fine-tune jobs and adapters carry their own columns.
  The scheduler jobs use the session directly and are not affected.
- `utils/credentials.py` keeps one API key per vector database or inference instance in two Secrets:
  `<kind>-<id8>-credentials` (`api-key`, for the chart)
  and `<kind>-<id8>-apikey-auth` (`<resource_id>`, for the gateway `apiKeyAuth`, `sanitize: false` so the
  workload also sees the key);
  `models/workload_credential.py` records only the Secret names and `shown_at`.
  `generate_secret(seed=str(resource_id))` is deterministic under `TEST_MODE`.
  `api/credentials.py` (`GET /v1alpha1/credentials/{vdb|inf}/{id}`) applies `Policy.can_write`,
  reveals the value once and afterwards only to admins with `?reveal=true`;
  the Secret is read before `shown_at` is stamped.
  `api/vectordb_instance.py` creates the credential before `VectorDBController.install`,
  removes it on delete and on a failed install,
  and passes it through `prepare_helm_values` as `credential`/`credential_secret_name`:
  Qdrant references the Secret (`apiKey.valueFrom`, the chart `lookup`s it, so it must exist before the install),
  Milvus renders it as the root password, Chroma has no auth (gateway only).
  `api/inference_instance.py` stores the credential right after the row is created
  and removes it after `controller.uninstall`, swallowing delete failures since the Helm release is already gone;
  only `controller/vllm_controller.py` reads it into the chart (`secretKeyRef` to `VLLM_API_KEY`) --
  HuggingFace, NIM and OPEA charts have no server-side API key, so those instances are gateway-protected only.
  `test_credentials.py` patches `utils.credentials.get_core_v1_client`;
  `test_app.py` and `test_controller.py` cover the router and the rendered values/policy names.
- `test_auth.py` signs tokens with a generated RSA key and patches `PyJWKClient.fetch_data`;
  the tests share one SQLite file, so every test removes the rows it creates.
- `api/chat.py` `POST /v1alpha1/chat/completions` is the OpenAI-compatible passthrough the UI's `/api/chat`
  route handler calls: the target comes from the `X-AIOps-Instance` header (400 without it, 404 unknown,
  `authorize_read` for the policy, 503 while the instance has no endpoint), the body is forwarded unchanged to
  `<instance.endpoint>/v1/chat/completions` with the workload credential in `x-api-key`
  (`find_credential` + `read_credential_value`), and the SSE stream is relayed when the body has `"stream": true`
  (upstream 4xx/5xx are forwarded with their text as `detail`, an unreachable upstream is a 502).
  `resolve_target` and `upstream_client` are module-level seams; `test_chat.py` patches them with an
  `httpx.MockTransport`. `AIOPS_CHAT_MOCK=true` (only with `TEST_MODE=true`) answers `You said: <last user
  message>` without any instance, for the Playwright fast tier. The gateway host uses the local CA, so the
  process needs `SSL_CERT_FILE` (httpx honours it; `make backend` sets it).
- `api/authz.py` `GET /v1alpha1/authz/route` is the gateway's ext-authz check: `utils/hostnames.py`
  `parse_hostname` turns the `Host` (or `X-Forwarded-Host`) into `(kind, id8, suffix)`
  (`nb`, `vdb`, `vdb ... -api`, `inf`; the parent domain from `gateway_settings()`, or the first label without it),
  the row is found with `cast(Model.id, String).like("%<id8>")`, notebooks need `Policy.can_write`
  and the other kinds `Policy.can_read`. 200 carries `X-Auth-User-Email`, `X-Auth-User-Sub`, `X-Auth-Org`;
  403 reuses `not_owner`; 404 covers unknown and unparsable hosts; one info log line per decision.
  `test_authz.py` imports the token helpers from `test_auth.py`.

## Conventions and gotchas

- The default namespace is `ai-stack`, overridable with `AIOPS_NAMESPACE`; controllers read it at call time.
- Schema changes are Alembic migrations, never edits to the baseline or `create_all`:
  edit the models, `uv run alembic upgrade head` against a scratch SQLite (`DATABASE_URL=sqlite:///./tmp/dev.db`),
  then `uv run alembic revision --autogenerate -m "<message>"` and review the file
  (`env.py` uses `render_as_batch=True`, so `ALTER`s are `op.batch_alter_table()` blocks that also work on SQLite;
  drop the spurious `NUMERIC` to `UUID` `alter_column` calls SQLite reflection produces).
  Data steps go through typed `sa.table()`/`sa.column()` objects so UUID binds work on SQLite and Postgres.
  `make db-migrate` applies them to the local Postgres; `uv run alembic history` shows the chain.
- Every `HTTPException` carries a human-readable string `detail`; the frontend shows it in a toast.
  Validation errors are 422, duplicates 409, an unreachable cluster 503.
- `pyproject.toml` turns `DeprecationWarning` into errors in tests; add a targeted `filterwarnings` entry rather
  than silencing them globally.
- Ruff line length is 79; `B008` (`Depends()` defaults) and `E501` are ignored on purpose.
- `chart_values/*.yaml` are reference values for humans and are not read by the code.
- Do not commit `config.yaml` manifests; copy `manifests/config.example.yaml` and fill the secrets locally.
