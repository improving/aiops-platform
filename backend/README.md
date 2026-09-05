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
| `AUTH_MODE`         | `oidc`                   | `oidc` validates bearer tokens; `disabled` needs `TEST_MODE=true`. |
| `OIDC_ISSUER`       | unset                    | Realm issuer, for example `https://auth.127.0.0.1.nip.io/realms/aiops`. |
| `OIDC_AUDIENCE`     | `aiops-api`              | Expected `aud` claim.                                        |
| `OIDC_JWKS_URL`     | `<issuer>/protocol/openid-connect/certs` | Where the signing keys are fetched from.     |
| `SSL_CERT_FILE`     | unset                    | CA bundle for the JWKS fetch (`infra/local/ca/ca.crt` on kind). |

## Authentication

Every route except `/health` needs a bearer token issued by the Keycloak realm
(`AUTH_MODE=oidc`, the default).
The API validates the signature against the realm JWKS (fetched lazily on the first request,
so the API starts while Keycloak is down), the issuer, the audience `aiops-api` and the lifetime
(60 seconds of leeway).
The JWKS fetch uses `urllib`, so a private CA must be in `SSL_CERT_FILE`;
`REQUESTS_CA_BUNDLE` has no effect on it.

On the first request a user row is created from the token (`sub`, `email`, `name`)
with a membership in the `default` organization.
The role comes from the realm roles in the token: `admin`, else `member`, else `viewer`.
A client-credentials token (no `email`, `azp` set) becomes the service user `svc:<client id>`
with the `member` role.
Viewers can read; members create and change what they own;
admins change everything in the organization.
`/reload-data` and `/refresh-db` need the `admin` role.
A missing or invalid token is a 401 with `WWW-Authenticate: Bearer`;
a resource of another user is a 403 `You do not own this <kind>`.

`AUTH_MODE=disabled` skips the token check and runs every request as the `dev` admin
(`dev@example.test`).
The backend accepts it only together with `TEST_MODE=true` and refuses to start otherwise;
the tests and the fast Playwright tier use it.

The gateway asks `GET /v1alpha1/authz/route` before it forwards a request to a deployed instance.
The endpoint reads the same bearer token and the `Host` header
(`X-Forwarded-Host` wins when present), finds the instance behind `nb-<id8>`, `vdb-<id8>`,
`vdb-<id8>-api` or `inf-<id8>` by the last eight hex characters of its id,
and answers 200 with `X-Auth-User-Email`, `X-Auth-User-Sub` and `X-Auth-Org`
(notebooks: the owner or an admin; vector databases and inference: any member of the organization),
403 `You do not own this <kind>`, or 404 for a host that is not an instance.
Each decision is one `authz host=... sub=... decision=...` log line.

To call the API from a script, get a token with the client credentials of `aiops-automation`
(secret `dev-automation-secret` in the local realm):

```bash
CA=infra/local/ca/ca.crt
TOKEN=$(curl -s --cacert $CA -d grant_type=client_credentials \
  -d client_id=aiops-automation -d client_secret=dev-automation-secret \
  https://auth.127.0.0.1.nip.io/realms/aiops/protocol/openid-connect/token | jq -r .access_token)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/v1alpha1/notebooks
```

To run the API against the local realm:

```bash
AUTH_MODE=oidc OIDC_ISSUER=https://auth.127.0.0.1.nip.io/realms/aiops \
SSL_CERT_FILE=../infra/local/ca/ca.crt uv run uvicorn app:app --reload
```

## Workload credentials

Each vector database and inference instance gets an API key (`utils/credentials.py`).
The key lives in two Kubernetes Secrets in the instance namespace,
`<kind>-<id8>-credentials` (`api-key`) for the chart
and `<kind>-<id8>-apikey-auth` (`<resource id>`) for the gateway `apiKeyAuth` policy;
the database keeps only their names and when the value was shown (`workload_credentials`).
`GET /v1alpha1/credentials/{vdb|inf}/{id}` returns `{"key": "api-key", "value": ..., "shown_at": ...}`
to the owner or an org admin once;
afterwards `value` is `null`, unless an admin asks with `?reveal=true`.
Under `TEST_MODE=true` the value is derived from the instance id, so the snapshots stay stable.

A vector database instance gets its key when it is created (`api/vectordb_instance.py`):
the Secrets are written before the Helm install and removed after the uninstall.
The Qdrant chart reads the key from `vdb-<id8>-credentials` (`apiKey.valueFrom.secretKeyRef`, a Helm `lookup`),
Milvus gets it as the `root` password (`common.security` in `extraConfigFiles`),
and Chroma 1.x has no built-in authentication, so only the gateway checks the key there.
The `-api` host carries a `SecurityPolicy` `<release>-api-apikey` (`apiKeyAuth`, header `api-key` or `x-api-key`)
that forwards the key to the workload; the browser host stays behind the shared OIDC policy.
`api/inference_instance.py` stores the credential right after the row is created, before `controller.install`,
and removes it after `controller.uninstall`.
The `inf-<id8>-apikey-auth` Secret protects the `inf-<id8>` gateway route the same way it does for vector databases
(`utils.gateway.ensure_apikey_policy`, wired into every engine controller through `base_controller.Controller`).
Only vLLM's chart reads the credential itself: its values reference the credentials Secret with a `secretKeyRef`
(`VLLM_API_KEY`, `controller/vllm_controller.py`), never the raw value.
HuggingFace's chart (`text-generation-inference`/`text-embeddings-inference`), NIM and OPEA have no server-side
API key of their own, so those instances rely on the gateway policy alone.

## Database migrations

Alembic owns the schema (`alembic.ini`, `alembic/`).
`init_db` runs `upgrade_to_head` at startup, so a fresh database gets every migration
and a database created before Alembic is stamped at `0001` first.
`make db-migrate` (from the repository root) applies the migrations to the local Postgres
without starting the API;
the CLI does not stamp, so a database created before Alembic needs `uv run alembic stamp 0001` once
(or one API start) before that.

To change the schema:

1. Edit the models in `models/`.
2. Generate a revision against a database that is at the current head:
   `mkdir -p tmp && DATABASE_URL=sqlite:///./tmp/dev.db uv run alembic upgrade head`, then
   `DATABASE_URL=sqlite:///./tmp/dev.db uv run alembic revision --autogenerate -m "<message>"`.
3. Review the file under `alembic/versions/`;
   autogenerate misses data changes,
   and against SQLite it reports a spurious `NUMERIC` to `UUID` type change on every id column
   (SQLite gives `UUID` columns numeric affinity), so drop those `alter_column` calls.
   `env.py` sets `render_as_batch=True`, so `ALTER` operations are wrapped in
   `op.batch_alter_table()` and also work on SQLite.
4. `./hack/format.sh` and `./hack/runtest.sh`.

## Local limitations

- Without a LoadBalancer provider (kind, colima) LoadBalancer services stay
  `<pending>`, so instance endpoints fall back to the cluster IP.
  The endpoint is stored once and the scheduler stops polling it,
  so an ingress IP that appears later is not picked up.
- Engines that pull from Hugging Face need `HF_API_TOKEN`.
- Notebook names are DNS-1123 labels of at most 32 characters;
  the kf-notebooks chart cuts `<name>-<id>-kf-notebooks-<name>` at 41 characters.
- The Milvus chart has `maintainers[0].url: milvus.io` in its `Chart.yaml`,
  which pyhelm3 rejects as a URL;
  the backend drops such informational fields before the install.
  The chart itself is heavy (etcd, MinIO, Pulsar) and needs a large cluster.

## Tests and lint

```bash
./hack/runtest.sh          # uv run pytest, TEST_MODE=true, AUTH_MODE=disabled
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
