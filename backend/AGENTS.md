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
Constructing an inference controller is cheap;
its Helm client runs `helm version` on first use (chart lookup, install, upgrade, uninstall),
so a test that reaches those passes `helm_client=` or needs the binary.
Plain test helpers live in the `testing` package (`tokens.py`, `rows.py`, `pods.py`); `conftest.py` carries the
shared fixtures (`oidc_client`, `tokens`, `notebook_controller`, `other_org`); no test module imports another.

## Architecture

- `app.py` calls `core.create_app()`, which registers the routers from `api/`, seeds the database
  (`db/db.py`, `init_db` → `load_initial_data` from `raw_data/*.csv`) and starts the APScheduler jobs in a
  FastAPI lifespan. `init_db` first runs the Alembic migrations (`db/migrate.py` `upgrade_to_head`,
  `alembic/versions/`) on the app engine; a database that predates Alembic is stamped `0001` first.
- `api/*.py` are the routers (`/v1alpha1/...`): `models`, `engines`, `hosts`, `inference_instance`,
  `inference_operations` (stop/resume/scale), `inference_status` (chart lookup, persisted status, the poller),
  `vectordb` and `vectordb_instance`, `notebooks`, `model_adapters`, `finetune`, `credentials`, `authz`, `chat`,
  `organizations`, `usage`. `instance_inspection.py` is not a router of its own; see "Operations".
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
  objects for every deployed instance: browser hosts (`nb-<id8>`, `vdb-<id8>`) join the shared
  `aiops-workloads-oidc` policy of their own namespace (a SecurityPolicy cannot target another namespace's
  route), SDK hosts (`vdb-<id8>-api`, `inf-<id8>`) get their own `apikey` policy, notebook routes get a
  `BackendTrafficPolicy` for WebSockets and `inf-` routes one with no request timeout (Envoy's default 15 s cut
  streamed answers). Every function is a no-op without `AIOPS_PARENT_DOMAIN`.
  Both route kinds fail closed (ADR 0002): each route is created and protected as a pair, and a failed create
  or attach raises a `GatewayPolicyError` subclass (`OidcPolicyError` for browser routes through
  `protect_browser_route`, `ApiKeyPolicyError` for SDK routes through `protect_sdk_route`), so install and
  upgrade never mislabel any of them as a Helm error. The route is deleted only when it is actually
  unprotected: `_protect_route` leaves it up when the policy already lists it, so re-confirming an existing
  policy on a later upgrade cannot take a running workload down. A failed attach cannot be recorded on the
  row, because the pods are healthy and the poller writes `Running` back within a tick. For an SDK route a missing credential Secret is one of
  those failures, not a reason to skip the policy: both create endpoints store the credential before they
  install, and most workloads check no key of their own (only Qdrant, Milvus and vLLM do).
  The client-Secret copy, the ReferenceGrants and the BackendTrafficPolicy stay best effort.
- `utils/kubernetes_utils.py` resolves the fallback service endpoint used when the gateway is not configured
  (loads kube config, file then in-cluster; LoadBalancer ingress IP or hostname, else the cluster IP,
  and `None` while nothing is known so the scheduler keeps polling).
  `paths.py` anchors `templates/`, `raw_data/` and `tmp/` on the package directory,
  so the app works from any working directory.
- `api/config.py` serves `GET /v1alpha1/config/ui` without a token (like `/health`), read from env at call
  time, so the platform chart configures the UI's embeds without rebuilding the image (`test_config.py`).

## Authentication

- `auth/settings.py` reads `AUTH_MODE` (`oidc` default, or `disabled`), `OIDC_ISSUER`, `OIDC_AUDIENCE`
  (`aiops-api`) and `OIDC_JWKS_URL` (default `<issuer>/protocol/openid-connect/certs`) at call time.
  `create_app` fails at startup on `AUTH_MODE=disabled` without `TEST_MODE=true` and on `oidc` without an issuer;
  the JWKS client (`auth/jwt.py`, `PyJWKClient(cache_keys=True)`) is built on the first request, so an unreachable
  Keycloak does not block startup.
  The fetch uses `urllib`: put a private CA in `SSL_CERT_FILE`.
- `auth/current_user.py` `get_current_user` is the dependency on every route except `/health`
  (`HTTPBearer(auto_error=False)`, 401s carry `WWW-Authenticate: Bearer`, an unreachable JWKS is a 503).
  It upserts `users` by `sub`; the membership role is set once when the membership is created
  (see "Tenancy, audit and tokens") and is never overwritten from the token.
  Client-credentials tokens (no `email`, `azp` set) become `svc:<azp>` with role `member`.
  In `disabled` mode every request is the `dev` admin, unless `TEST_MODE=true` also honours `X-Dev-User`
  (see "Tenancy, audit and tokens"). `require_role(...)` wraps it
  (`require_writer` on create routes, `require_platform_admin` on `/reload-data` and `/refresh-db`).
  `auth/roles.py` (role constants) and `auth/errors.py` (`unauthorized`) are split out so `dev_users.py` can
  raise a 401 without importing `current_user.py`, which imports `dev_users.py`.
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
- `api/chat.py` serves `GET /v1alpha1/chat/targets` and `POST /v1alpha1/chat/completions`, `/v1alpha1/embeddings`
  and `/v1alpha1/rerank`. A target is a deployed instance (`inst-<id8>`) or, since Phase 2b, a hosted provider
  model (`prov-<id8>/<model>`, `<model>` may itself contain `/` — OpenRouter ids do — so only the first `/`
  after the id8 is a separator); `find_target` resolves either into a `Target` dataclass (`kind`, `org_id`,
  `litellm_model_id`, `endpoint`, `upstream_model`, `api_key_lookup`) after `authorize_read` on the underlying
  row (`utils/ids.find_by_id8` on `DBInferenceInstance` or `models.provider.Provider`). `list_targets` is
  `list_instance_targets` (the caller's organization's registered instances, plus, without LiteLLM, ready `llm`
  instances with an endpoint, `via: "litellm"` or `"direct"`) followed by `list_hosted_targets` (every enabled
  model of every enabled provider in the caller's organization, `via: "litellm"` always, since hosted models
  have no direct route); every target entry carries both `instance_id` and `provider_id`, one of them `null`.
  When the target is registered in LiteLLM (`litellm_model_id` set) every route forwards to the proxy with the
  organization's virtual key (`org_key` → `utils.litellm.ensure_org_key`, `_relay_litellm`); otherwise chat
  falls back to the Phase 1 direct passthrough to `<target.endpoint>/v1/chat/completions` with the workload
  credential in `x-api-key` (`_relay_direct`, `target.api_key_lookup()`) — a hosted target has no `endpoint`
  and answers 503 "Hosted models need LiteLLM" — and embeddings/rerank answer 503 without LiteLLM regardless of
  target, since there is no direct route for them either. Both relays stream the SSE answer when the body has
  `"stream": true` (upstream 4xx/5xx forwarded with their text as `detail`, an unreachable upstream a 502).
  `find_target`, `litellm_client`, `org_key` and `instance_api_key` are module-level seams; `test_chat.py`
  patches them (`find_target` with a `Target` built by the test's own `_target()`/`_add_hosted_model()`
  helpers), and patches `litellm_client`'s `LiteLLMClient` with an `httpx.MockTransport` for the LiteLLM
  path. `AIOPS_CHAT_MOCK=true` (only with `TEST_MODE=true`) serves one target `inst-mock` plus
  `list_hosted_targets` and answers chat with `You said: <last user message>`, embeddings with a 4-float
  vector per input and rerank with the documents reversed, without any instance, for the Playwright fast tier.
  The gateway host uses the local CA, so the process needs `SSL_CERT_FILE` (httpx honours it; `make backend`
  sets it). `user_key(user)` (`str(user.id)`, an opaque id rather than the email, so no email reaches LiteLLM's
  database, its metrics labels or an upstream provider) is the identity every route forwarded through LiteLLM
  carries as the OpenAI `user` field (`_forward`, LiteLLM branch only -- the direct passthrough carries no
  such field); LiteLLM records it as the spend log row's `end_user`. `target_labels(db, user)` maps every
  `inst-<id8>`/`prov-<id8>/<model>` name the caller's organization can spend on to its display label, for the
  usage endpoint below -- unlike `list_targets` it never calls the cluster and keeps disabled provider models,
  which may still carry historical spend.
- `utils/litellm.py` is the LiteLLM proxy client and the platform's naming rules in it. `litellm_settings()`
  reads `LITELLM_URL`/`LITELLM_MASTER_KEY`; `get_client()` is `None` without both, and every caller treats that
  as "skip the proxy" rather than an error. `_ROUTES` maps `(engine, category)` to the LiteLLM provider prefix,
  path suffix and mode (`instance_litellm_params`); NIM's reranker and OPEA have no route. `LiteLLMClient` wraps
  `/model/new`, `/model/delete`, `/team/new`, `/team/delete`, `/key/generate`, `/key/delete` and `/team/info`
  behind a sync `httpx.Client` (`request()` also supports a streamed response the caller must close, and its
  `response.extensions["aiops_client"]`); every non-2xx or transport error raises `LiteLLMError`.
  `ensure_org_key(db, org, core_v1=None)` creates the organization's LiteLLM team and one virtual key on first
  use, stores the key in Secret `org-<id8>-litellm-key` (`utils/credentials.py` `_secret_body`/`_apply_secret`,
  key `"key"`) and caches it in-process for 300 s (`_org_key_cache`, cleared by tests).
  `api/inference_instance.py` `register_instance`/`unregister_instance` call `get_client()` and
  `instance_litellm_params` around `controller.service_url(instance, engine_chart)` (the in-cluster
  `http://<service>.<namespace>.svc:<port>` URL, `base_controller.Controller.service_url`) to register/delete
  the instance's LiteLLM model (`inst-<id8>`, `instance_model_name`) right after install and before uninstall;
  both are wrapped in `asyncio.to_thread` and are best effort — a LiteLLM outage is logged and never fails a
  launch or a delete. Migration `0005` adds `inference_instances.litellm_model_name`/`litellm_model_id` and
  `organizations.litellm_team_id`/`litellm_key_secret_name`/`budget_usd`. Since Phase 2b, `hosted_model_name`
  and `hosted_litellm_params` are the same naming and `/model/new` params for hosted provider models
  (`api/providers.py`), and `LiteLLMClient.update_team_budget(team_id, max_budget)` calls `POST /team/update`
  with `{"team_id", "max_budget", "budget_duration": "30d"}` (`max_budget: None` clears the cap — verified
  against a throwaway team on the local proxy: `/team/info` reports `max_budget: null` back after that call).
  `LiteLLMClient.spend_logs(team_id, start, end)` pages `GET /spend/logs/ui` (`start_date`/`end_date` formatted
  `YYYY-MM-DD HH:MM:SS` UTC, `page_size=500`, at most 20 pages) and returns `(rows, capped)`; `capped` is true
  when a page reports `total_is_capped` or the 20-page ceiling is hit before the proxy's own last page.
- Hosted providers (Phase 2b): `utils/secret_store.py` is the `SecretStore` seam for a provider's API key —
  `KubernetesSecretStore` (the same Secret shape as `utils/credentials.py`, `core_v1` resolved lazily so
  constructing the store never touches the kubeconfig on its own) or `MemorySecretStore` (a module-level dict);
  `get_secret_store()` returns the memory store only for `AIOPS_SECRET_STORE=memory` with `TEST_MODE=true`
  (otherwise `RuntimeError`), the Kubernetes store otherwise. `utils/model_prices.py` `load_prices()` caches
  LiteLLM's public `model_prices_and_context_window.json` in-process (`TEST_MODE` reads
  `raw_data/model_prices.sample.json` instead of fetching it, and a failed fetch outside `TEST_MODE` logs and
  returns `{}`); `lookup_price(kind, model)` tries `model`, `<kind>/model` then `openrouter/model`.
  `utils/providers.py` has `PROVIDER_KINDS` (`openai`, `anthropic`, `gemini`, `groq`, `openrouter`),
  `provider_secret_name(provider_id)` (`prov-<id8>-credentials`), `discover_models(kind, api_key, base_url)`
  (calls the provider's own model-listing endpoint, raises `ProviderError` on a rejected key or an unreachable
  provider) and the local-only `capability_for`/`enrich` (`utils/model_prices.lookup_price`): a model's
  capability is its price entry's `mode` when that is `chat` or `embedding`, `"chat"` when the model is not in
  the catalog, and dropped (excluded from discovery) for every other known mode (tts, image, moderation,
  audio, ...).
  `api/providers.py` (`/v1alpha1/providers`, `require_admin` on every write, `authorize_read` + `org_scope` on
  every read) creates a `Provider` row, writes its key to the secret store, then registers each requested
  model in LiteLLM as `prov-<id8>/<model>` before adding the `ProviderModel` rows and committing — in that
  order, so a duplicate name (`uq_providers_org_name`, caught as `IntegrityError` on an explicit `db.flush()`
  before the Secret is even written) is a clean 409, and a `LiteLLMError` during registration deletes the
  models already registered and the Secret, rolls the transaction back, and answers 502; `PATCH` with a new
  `api_key` re-registers every model with the new key before deleting the old registrations, so a failure
  there leaves the old key and registrations untouched; `DELETE` unregisters best effort (like
  `unregister_instance`) and always deletes the Secret and rows. `POST /discover` (no row yet) and
  `POST /{id}/discover` (reads the stored key back from the secret store) return `discover_models` merged with
  local price fields; `AIOPS_CHAT_MOCK=true` short-circuits both to two canned models (`mock-chat-1` chat,
  `mock-embed-1` embedding) and registration to `litellm_model_id="mock"`, for the Playwright fast tier.
  Responses never carry the key, only `has_key: true`.
  Migration `0006` (`down_revision = "0005"`) adds `providers` and `provider_models`
  (`provider_models.provider_id` cascades in the ORM relationship and the FK, `ondelete="CASCADE"`, since
  SQLite does not enforce FK cascades on its own).
  `api/chat.py` and `api/usage.py` are the two callers outside `api/providers.py`: see their own bullets.
- `api/usage.py` (its own router, next to the organizations one; imports `_current_org`/`_org_budget` from
  `api/organizations.py`, never the reverse; `test_usage.py`/`test_chat.py` patch `get_client`/`ensure_org_key`
  on it) is the spend and budget half of Phase 2b (routes and response shapes in docs/api.md); `PUT` stores
  `budget_usd` on the row before it (outside `AIOPS_CHAT_MOCK`) calls `LiteLLMClient.update_team_budget`.
- Usage: `GET /v1alpha1/organizations/current/usage?days=30` (any member, `days` clamped `1..90`, 422 outside
  it) reads `LiteLLMClient.spend_logs` for the caller's organization team since `days - 1` days ago at 00:00
  UTC through now, then aggregates by `(display name, model_group, day)`.
  Rows written while `user_key` returned the email (before `4f7a7f2` switched it to the user id) and rows written after both resolve to the same display name and land in one row.
  Members keep only their own rows
  (`spend_logs(..., end_user=user_key(user))` asks LiteLLM for just those; `_visible_to` is the backstop)
  and never see an unattributed row (empty `end_user`,
  made before this endpoint's `user` field shipped, or with the master key); admins see every row, including
  the unattributed ones as `user: null`; each row's `user` is the email (else name, else subject) from the `users`
  table for the ids LiteLLM stored (`_user_names`), or the raw `end_user` value when no user row matches.
  A member's request is filtered server-side by user id, so a member does not see their own email-keyed rows merged in (a known asymmetry, follow-up).
  Response: `scope` (`"organization"` for an admin, `"user"` for a
  member), `capped` (from `spend_logs`), `totals` (`requests`, `prompt_tokens`, `completion_tokens`, `spend`),
  `by_target` (one entry per target, sorted by spend then requests, both descending) and `rows` (one entry per
  `(user, target, day)`, sorted by day descending, then user, then target — a stable sort by `(user, target)`
  first, then a stable re-sort by `day` alone, does this without a synthetic descending key on a date string).
  Every entry's `label` comes from `target_labels`, the raw target name when the row's target is not (or no
  longer) one of the organization's. `AIOPS_CHAT_MOCK=true` serves three canned rows for `inst-mock` (two for
  the caller, one for `someone@example.com`) through the same visibility and aggregation code, so the fast
  tier's dev admin sees three rows and two users. 503 without a LiteLLM client, 502 on `LiteLLMError`.
- `api/authz.py` `GET /v1alpha1/authz/route` is the gateway's ext-authz check: `utils/hostnames.py`
  `parse_hostname` turns the `Host` (or `X-Forwarded-Host`) into `(kind, id8, suffix)`
  (`nb`, `vdb`, `vdb ... -api`, `inf`; the parent domain from `gateway_settings()`, or the first label without it),
  the row is found with `utils.ids.find_by_id8` (also used by `api/chat.py`), notebooks need `Policy.can_write`
  and the other kinds `Policy.can_read`. 200 carries `X-Auth-User-Email`, `X-Auth-User-Sub`, `X-Auth-Org`;
  403 reuses `not_owner`; 404 covers unknown and unparsable hosts; one info log line per decision.
  `test_authz.py` imports the token helpers from `test_auth.py`.

## Tenancy, audit and tokens

Routes, parameters and response shapes are in docs/api.md; here, where things live and what bites:

- `auth/current_user.py` `resolve_user` picks the active organization (`X-Org`, else first membership by
  `created_at` then slug) and accepts pending invitations for the user's verified email; the realm role only
  ever sets a *new* membership's role (see Authentication).
- `auth/dev_users.py`: `X-Dev-User` (`AUTH_MODE=disabled` + `TEST_MODE=true`) names `dev`/`alice`/`bob`/`viewer`/`outsider`;
  `ensure_dev_memberships` reseeds them every request, so a removed membership reappears on the next call.
- `api/organizations.py` also owns membership admin and invitations; `api/audit.py` the audit log;
  `api/tokens.py` personal tokens.
- `audit/middleware.py` (outermost) writes one `AuditEvent` per non-`GET`/`HEAD`/`OPTIONS` `/v1alpha1/` request
  (except chat, embeddings, rerank, `authz`); `audit/events.py` derives kind/id/action/actor from the request.
- `auth/tokens.py`: `aiops_<8>_<32>`, `sha256(secret)` stored, `hmac.compare_digest` compared; resolved before
  the JWT path.
- Tests: `test_tenancy.py`, `test_audit.py`, `test_tokens.py` (oidc mode; disabled mode never resolves a
  token). Rows inserted directly use fixed UUIDs so `genid` counters and snapshot ids do not move.

## Operations

Routes, parameters and the day-2 action semantics are in docs/api.md; here, where things live and what bites:

- `utils/instance_status.py`: `mark_pending`/`mark_failed` (`last_error` capped at 4000 chars), `apply_pod_status`
  (a pod with a `deletion_timestamp` counts for neither ready nor failed; only `resume` leaves `Stopped`) and
  `refresh_stale` (one controller per scheduler tick). `NULL` status means "not looked at yet".
  `READ_ONLY_STATUS_FIELDS` (inference only) is the columns a PUT may never set.
- One `check_pod_status_and_readiness(instance, db, controller=None)` signature across the three routers;
  `test_auth.py` monkeypatches it by name in `api.vectordb_instance` and `api.inference_instance`.
  `utils/kubernetes_utils.py` `PodStatus` is the only return type, there is no tuple shim.
- `api/instance_inspection.py` (`InstanceKind`, `add_inspection_routes`) is the shared logs/events/restart
  layer; `utils/pod_inspection.py` does the Kubernetes reads. `api/inference_operations.py` is stop/resume/scale
  on top of it; `api/inference_status.py` is the chart lookup and status-polling leaf both of it and
  `api/inference_instance.py` import from.
- Pod logs are read with `_preload_content=False` and decoded in `utils/pod_inspection.py`:
  the client declares a `str` return, so on a body it did not decode it hands back `str(bytes)`,
  and the UI then shows `b'...'` with every newline as the two characters backslash and n.
  `testing/pods.py` `fake_core` models that, so a test that drops the flag fails.
- `test_operations.py` and `test_pod_inspection.py` cover all of this with mocked Helm and Kubernetes clients.

## Model registry (Phase 3)

- `models` grew from a flat catalog into a registry: `source` (`manual`, `huggingface`, `ollama`, `openrouter`),
  `source_id` (the id at that source, `NULL` for a manual row), `license`, `parameters`, `context_length`,
  `capabilities`/`formats`/`tags` (`JSON`, `NOT NULL`, default `[]` -- pass Python lists through them, never
  `json.dumps()` first, or the column double-encodes the value into a string), `status` (`draft`, `published`,
  `deprecated`; only `published` rows are the members' catalog), `synced_at`/`sync_error`/`raw` (sync
  bookkeeping) and `org_id` (`NULL` means global, every organization's catalog; a non-`NULL` row is that
  organization's own addition -- `api/models.py` `catalog_scope` filters on this directly, not
  `auth.policy.org_scope`, which maps `NULL` to the *default* organization only and would hide the global
  catalog from every other organization). `model_serving_options` (`models/serving_option.py`) is one row per
  `(model_id, engine)`: which engine can run the entry and the `reference` its controller needs (an Ollama tag,
  a Hugging Face repo id, a `hf.co/<repo>:<quant>` GGUF pull, or a hosted provider model id such as an
  OpenRouter id, which has no matching `engines` row). Migration `0007` (`down_revision = "0006"`) adds all of
  this plus `inference_instances.reference`, and backfills every pre-existing `models` row's `capabilities`,
  `formats` and serving options from `category` and whether `modelId` looks like an Ollama tag (a `:` and no
  `/`); on a fresh `TEST_MODE` database the migration runs before any row exists, so that backfill is a no-op
  there and the CSV/YAML-seeded rows get their serving options from `load_models` (below) instead.
- `instance.reference` (`models/inference_instance.py`) is the serving option's `reference`, set on
  `create_inference_instance` when the request carries a `serving_option_id`
  (`schemas/inference_instance.py` `InferenceInstanceCreateSchema`, verified to belong to the instance's model
  before it is persisted). **Every place that renders or forwards a model id reads
  `instance.reference or instance.model.modelId`**, never `instance.model.modelId` alone: the controllers
  (`ollama_controller.py` `models.pull`, `hf_controller.py`/`vllm_controller.py`/`opea_controller.py`
  `modelID`/`model`), `api/inference_instance.py` `register_instance` (the LiteLLM `model` param), and
  `api/chat.py` `_find_instance_target` (`upstream_model`, the direct-path substitution) and
  `list_instance_targets` (`"model"`).
- The seed is `raw_data/models.yaml`, not a CSV: `db/db.py` `load_models` reads it (`path=` is a test-only
  override) and upserts by `(source, source_id)` when `source_id` is set, else by `modelId`, matching serving
  options by `(model, engine)`; it never deletes a row, so a model or option dropped from the YAML stays in the
  database until an admin removes it. `registry/export.py` `export_registry(db)`/`write_registry(db, path)` is
  the inverse: the *global* catalog (`org_id IS NULL`) only, sorted by `source`, then `source_id`, then `name`,
  with a stable per-entry key order, as YAML text -- `scripts/registry_export.py`
  (`uv run python scripts/registry_export.py` from `backend/`; a `make registry-export` target that runs it
  against the local Postgres is still pending) writes it to `raw_data/models.yaml`.
  `test_registry_export.py` guards both directions: exporting the seeded test database
  and reloading it round-trips to the same YAML, and the *committed* `raw_data/models.yaml` already equals its
  own export (a hand edit that reorders entries would fail this and must be re-exported instead).
- Importers (`registry/`) are pure functions from a source's JSON to a `registry.entry.RegistryEntry`
  (`source, source_id, name, description, category, subcategory, size, license, parameters, context_length,
  capabilities, formats, tags, raw, serving_options: list[tuple[engine, reference]]`); the HTTP fetch lives in
  one thin client per source, built with `verify=certifi.where()` (`make backend` points `SSL_CERT_FILE` at the
  local CA only, which would fail TLS to every public host otherwise). `registry/huggingface.py`
  `parse_model()`/`search()`/`fetch()`: category from `pipeline_tag` (falling back to `config.architectures`
  ending in `ForCausalLM`), license from `cardData.license` or a `license:` tag, `parameters` from
  `safetensors.total`, a GGUF repo (`library_name == "gguf"` or a `.gguf` sibling) picks one file -- `Q4_K_M`
  when the repo has it, else the first `.gguf` sibling -- for both `size` and the Ollama serving option's quant
  suffix, a gated repo (`gated` truthy) gets no serving options and a `"gated"` tag. `registry/ollama.py`
  `fetch(reference)`: `reference` is `name` or `name:tag` (`tag` defaults to `latest`), reads the OCI manifest
  (`GET https://registry.ollama.ai/v2/library/{name}/manifests/{tag}`, no tag-listing endpoint, so there is no
  real search: the "Add Ollama model" query is the full reference and the answer is this one preview), `size`
  is the `application/vnd.ollama.image.model` layer's size, capability is `embedding` for a small known-name
  set (`ollama.EMBEDDING_MODEL_NAMES`) and `chat` otherwise. `registry/openrouter.py` `list_models()`: every
  entry is category `llm`, `capabilities` gains `"vision"` when `image` is an input modality, `raw` keeps only
  the pricing. `registry/sources.py` `search(source, query, limit)`/`fetch(source, source_id)` is the
  source-name dispatcher `api/registry.py` calls; every source raises `registry.entry.SourceError(status,
  detail)` on a rejected (429, with the `retry-after` header folded into `detail`) or unreachable request.
  `test_registry_importers.py` exercises every parser against a fixture recorded from the real API
  (`test_fixtures/*.json`, trimmed to a handful of entries) and every `search`/`fetch` against an
  `httpx.MockTransport`; importers never touch the network in tests.
- `api/registry.py` (`/v1alpha1/registry`, `require_platform_admin` on every write; `GET /` is open to members but
  always filtered to `status == "published"` for them, `?status=&source=&capability=&q=` for an admin) is the
  admin surface: `GET /search?source=huggingface|ollama|openrouter&q=&limit=` returns previews
  (`RegistryEntryPreviewSchema`, `already_imported` looked up by `(source, source_id)`);
  `POST /import {source, source_id, status?, provider_id?}` fetches and creates the row (`status` defaults to
  `draft`) and its serving options, 409 on a repeat `(source, source_id)`; an `openrouter` import additionally
  requires `provider_id` of an enabled OpenRouter provider (Phase 2b) and registers the model under it
  (`_register_openrouter_model`, reusing `api.providers._register`/`_add_model_row`) so it becomes a chat
  target too. `POST /manual` and `api/models.py` `POST /v1alpha1/models` both go through
  `registry/manual.py` `create_manual_model` (source `manual`, always `published`, no source to sync from), so
  a model created either route is exactly the same shape. `PATCH /{id}` replaces serving options only when the
  request carries them. `POST /{id}/sync` re-fetches from the row's source and calls
  `registry.sync.apply_sync_fields` (license, parameters, context_length, size, formats, tags, raw, `synced_at`
  -- never `name`/`description`, which an admin may have hand-edited). `DELETE /{id}` answers 409 (naming every
  blocking kind) when inference instances, model adapters or fine-tune jobs still reference the row.
  `AIOPS_CHAT_MOCK=true` (`api.chat.chat_mock_enabled`) makes `search`/`fetch` read `test_fixtures/*.json`
  instead of the network (one canned entry per source; Hugging Face's is `Qwen/Qwen3-0.6B-GGUF`), for the fast
  Playwright tier and `test_registry_api.py`.
- `registry/sync.py` `sync_published(db)` is the daily best-effort resync of every published, source-backed
  (`source_id IS NOT NULL`) row: a source outage on one row sets `sync_error` (and is logged) without raising,
  so it never blocks the rest; a later success clears it. `core.py` schedules it every
  `REGISTRY_SYNC_INTERVAL_SECONDS` (default 86400; `0` disables it; like every other scheduled job, `TEST_MODE`
  never builds the scheduler at all) alongside the three endpoint-polling jobs -- `test_lifespan_runs_scheduler`
  asserts 4 jobs, not 3.

## Conventions and gotchas

- The default namespace is `ai-stack`, overridable with `AIOPS_NAMESPACE`; controllers read it at call time.
- Schema changes are Alembic migrations, never edits to the baseline or `create_all`:
  edit the models, `uv run alembic upgrade head` against a scratch SQLite (`DATABASE_URL=sqlite:///./tmp/dev.db`),
  then `uv run alembic revision --autogenerate -m "<message>"` and review the file
  (`env.py` uses `render_as_batch=True`, so `ALTER`s are `op.batch_alter_table()` blocks that also work on SQLite;
  drop the spurious `NUMERIC` to `UUID` `alter_column` calls SQLite reflection produces).
  Data steps go through typed `sa.table()`/`sa.column()` objects so UUID binds work on SQLite and Postgres.
  `make db-migrate` applies them to the local Postgres; `uv run alembic history` shows the chain.
- Migration `0008` is the single head; a stream's column goes into `0008` on `feat/enterprise-schema` and is
  merged forward, never its own migration, so `upgrade_to_head` never sees a fork; `test_migrations.py` checks
  every model agrees column for column.
- Every `HTTPException` carries a human-readable string `detail`; the frontend shows it in a toast.
  Validation errors are 422, duplicates 409, an unreachable cluster 503.
- `pyproject.toml` turns `DeprecationWarning` into errors in tests; add a targeted `filterwarnings` entry rather
  than silencing them globally.
- Ruff line length is 79; `B008` (`Depends()` defaults) and `E501` are ignored on purpose.
- `chart_values/*.yaml` are reference values for humans and are not read by the code.
- Do not commit `config.yaml` manifests; copy `manifests/config.example.yaml` and fill the secrets locally.
