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
  It also carries `context_length`, the window the target serves in tokens, for the chat page's meter:
  an instance's own `max_model_len` argument (`instance_context_length`, vLLM only --
  no other controller sets the served window, so they answer `null` rather than the registry's figure).
  Never the engine default: the controllers merge the defaults at every render, so an instance without the argument follows the default of the day,
  and the seed changed once (4192 to 16384) under a running instance. `api/inference_instance.py` `_record_window` therefore writes the default
  into a new vLLM instance's own arguments at create; an instance from before that answers `null` until its argument is set.
  The other source is a hosted model's `ProviderModel.context_length`.
  `tools` says whether the target answers a request that carries `tools`: `instance_tool_calling` reads the vLLM flag
  `--enable-auto-tool-choice` from the instance's own arguments (vLLM answers 400 without it) and is `null` for every other engine,
  because with Ollama it depends on the model; `hosted_tool_calling` reads `supports_function_calling` from the price catalog (`ModelPrice.tools`), at list time,
  so `utils/model_prices.py` does not repeat a failed fetch for `RETRY_AFTER` seconds. `null` means unknown, and the chat page lets the user try.
  The chat mock runs a tool loop for the fast tier: with `tools` in the request and a last user turn that starts with `call `,
  it calls the first tool with the rest of the text as the first argument; after a `tool` message it answers `Tool said: <content>`.
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
  A mock stream ends with a usage chunk (`choices: []`, one token per word) when the body asks for it with
  `stream_options.include_usage`, as the UI's route handler does, so the fast tier sees the same shape vLLM and LiteLLM send.
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
  `ensure_user_key(db, org, user, core_v1=None)` is a member's own key in that team (`user_id` = the platform user id,
  alias `org-<slug>-usr-<id8>-langflow`, Secret `org-<id8>-usr-<id8>-litellm-key`, cache `_user_key_cache`):
  what `utils/langflow.py` writes into the member's Langflow account, so LiteLLM records who spent on calls that name no `user`,
  and what `delete_user_key(org, user_id)` revokes alone when `remove_member` removes them (502 and the member stays when that fails).
  `rotate_org_key(db, org, core_v1=None)` replaces that key (new key into the Secret and the cache, then the
  old one deleted in LiteLLM); `api/organizations.py` `remove_member` calls it before deleting the membership,
  because a Langflow account provisioned before members had keys of their own holds a copy of it that cannot be
  revoked on its own, and answers 502 without removing anyone when the rotation fails. Two consequences:
  members' Langflow copies stop working until their next Develop page load, and another backend replica
  serves the old key from its cache for up to 300 s.
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
  A row belongs to the owner of its key when the key has one, else to the request's `user` (`_row_user`):
  a member's own key (`ensure_user_key`, what their Langflow account calls LiteLLM with) names them whatever the request says,
  and the request is theirs to write, so the key owner is the value they cannot choose;
  the organization's key has no owner and its requests come from the backend, which sets `user`.
  Members keep only their own rows
  (two queries, `spend_logs(..., end_user=id)` and `spend_logs(..., user_id=id)`, merged by `request_id`; `_visible_to` is the backstop)
  and never see an unattributed row (no key owner and an empty `end_user`:
  made before this endpoint's `user` field shipped, with the master key, or by a Langflow account provisioned before members had keys of their own); admins see every row, including
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
  LiteLLM also logs every MCP call as a spend row named like a model (`MCP: list_tools`, `MCP: <alias>-<tool>`, no user, no tokens). They are not model requests:
  `_is_mcp_row` keeps them out of `totals`, `by_target` and `rows`, and `tools` lists them by server and tool (`_aggregate_tools`; the alias becomes the server's name, a deleted server keeps its alias, `list_tools` is left out).
  `utils/mcp_relay.py` sends `x-litellm-end-user-id: <user_key>` with every MCP request, which LiteLLM writes into the row's `end_user` (measured), so a tool call is visible like a model request: a member's own, an admin's all, and the rows from before that (no user) only to an admin. The mock has three such rows.
- `api/authz.py` `GET /v1alpha1/authz/route` is the gateway's ext-authz check.
  The `langflow` host is a member rule (`_authorize_langflow`): any browser session is allowed, service
  accounts and personal tokens answer 403 with `NOT_A_PERSON`, because that policy passes a bearer straight
  through to Langflow (ADR 0002). For instance hosts: `utils/hostnames.py`
  `parse_hostname` turns the `Host` (or `X-Forwarded-Host`) into `(kind, id8, suffix)`
  (`nb`, `vdb`, `vdb ... -api`, `inf`, and `langflow` with an empty id;
  the parent domain from `gateway_settings()`, or the first label without it),
  the row is found with `utils.ids.find_by_id8` (also used by `api/chat.py`), notebooks need `Policy.can_write`
  and the other kinds `Policy.can_read`. 200 carries `X-Auth-User-Email`, `X-Auth-User-Sub`, `X-Auth-Org`;
  403 reuses `not_owner`; 404 covers unknown and unparsable hosts; one info log line per decision.
  `test_authz.py` takes its token helpers from `testing/tokens.py`.

- `utils/langflow.py` and `api/langflow.py` (`POST /v1alpha1/langflow/provision`, docs/api.md) provision the
  caller's Langflow account: Langflow's "OpenAI Compatible" provider variables `OPENAI_COMPATIBLE_BASE_URL`
  (`LITELLM_CLUSTER_URL`, else `LITELLM_URL`, plus `/v1`; written first, since the key's check reads it) and
  `OPENAI_COMPATIBLE_API_KEY` (`ensure_org_key`), created or updated in place. The backend holds no Langflow
  credential: it forwards the caller's own bearer (the `HTTPBearer` dependency from `auth/current_user.py`),
  which is why the endpoint answers 409 to anything but a browser session (`CurrentUser.is_browser_session`,
  the same predicate `api/authz.py` uses for the Langflow host), before it even looks at LiteLLM.
  The model list comes from `api.chat.list_targets(db, user, probe=False)` (names and labels, no pod probe)
  and is passed in, so `utils/langflow.py` never imports from `api/`. `LANGFLOW_API_URL` is the
  gateway host locally (`passThroughAuthHeader`) and the Service in the chart. `LangflowError` (Langflow's own
  detail, 502) and `LiteLLMError` (502) are the two failure shapes; `AIOPS_CHAT_MOCK=true` answers with `inst-mock`
  for the Playwright fast tier. `test_langflow.py` fakes Langflow with `httpx.MockTransport`.
  With `AIOPS_BACKEND_CLUSTER_URL` set (the address a pod reaches the backend at) and a writer role, provisioning also writes `AIOPS_MCP_URL` (`<that>/v1alpha1/mcp`) and `AIOPS_MCP_TOKEN`,
  so a flow uses the organization's tools through the one endpoint and not LiteLLM's `/mcp` with the model key, which would go around the viewer rule and a member's own credentials.
  The token is a personal token of scope `mcp` named `langflow` that the platform manages (`auth/tokens.py` `ensure_managed_token`): a stored token cannot be read back,
  so the caller says whether Langflow still has the variable; a new one is minted only when it does not or the token has under 30 days left,
  and the old rows are deleted, not revoked, because this runs on every Develop page load. Langflow keeps one variable for the user whatever the organization, so "the holder has it" also needs the newest `langflow` token of the user to be this organization's; after a provision in another organization a new one is minted here. `mint_token` is the one mint path, shared with `api/tokens.py`.

- MCP servers (`api/mcp.py` is the registry, `api/mcp_endpoint.py` the `/v1alpha1/mcp` endpoint, `utils/mcp_mock.py` the test doubles of `AIOPS_CHAT_MOCK`; the endpoint takes `litellm_client` and `org_key` through `api.mcp`, so tests patch them there for both; routes in docs/api.md, design in `docs/superpowers/specs/2026-09-19-tools-and-mcp-design.md`, ADR 0010):
  an admin registers a remote MCP server, the hosted-provider way (row, Secret, LiteLLM, commit; a failure undoes the earlier steps, 502).
  `models/mcp_server.py` has `McpServer` and `McpCredential`; the credential is a table of its own (`user_id` NULL = the organization's shared one,
  two partial unique indexes because NULLs are distinct), so a member's own credential is a new row and not a new column.
  `utils/mcp.py`: the LiteLLM alias `<name without _><server id8>`, letters and digits only (the proxy names tools `<alias>-<tool>`, so the first `-` ends the alias; and the alias is part of the header name `x-mcp-<alias>-authorization`, where Envoy refuses a `_`),
  and `validate_server_url` (https only; no loopback, private, link-local, metadata or cluster-internal address, checked after resolution;
  a host in `AIOPS_MCP_ALLOW_INSECURE_HOSTS` skips both rules, which `make backend` sets for the local test server; `resolve=False` in mock mode).
  `utils/mcp_credentials.py`: Secret names (`mcp-<id8>-credentials`, `mcp-<id8>-usr-<uid8>-credentials`), `state(server, user)` from the rows alone (what the list shows),
  and `resolve(server, user, alias)`, the one place that says which headers a caller's request carries: nothing for `none` and `shared` (LiteLLM holds a copy of the shared credential as `static_headers`),
  and for `per_user` the member's value from their Secret (cached 60 s in this process: another backend replica serves a replaced or removed value for up to that long, the same class as `_org_key_cache`) as `x-mcp-<alias>-<header>`, which the proxy forwards to that server for that call only
  (measured with the `whoami` tool of `infra/local/mcp/test-server.yaml`: two callers, two credentials, no mixing; a header name with `_` was refused by Envoy, hence the alias form).
  A `per_user` server is registered in the proxy without a credential; the admin's value of the create is their own and sets the header shape (`user_auth_type`, `user_auth_header`, migration `0010`).
  `PUT .../credential` tries the value through discovery before it stores it. `remove_member` (`api/organizations.py`) calls `delete_for_user` first and keeps the member on a failure, like the LiteLLM key.
  `utils/litellm.py` has the proxy's MCP calls (`/v1/mcp/server`, which is not in its OpenAPI document; `/team/update` with `object_permission.mcp_servers`;
  `/mcp-rest/test/tools/list` for discovery, which answers 200 with `error: true` on a failure). Always send `transport`: the proxy's default is `sse`.
  `_team_id` runs before the first change of a request: `ensure_org_key` commits when it creates the team, and a row flushed before it survived the rollback of a failed registration (found on the live stack).
  `/v1alpha1/mcp` (GET, POST, DELETE; `require_writer`, so a viewer gets 403) is the one door for every client. `utils/mcp_relay.py` forwards an allow-list of headers only
  (never `Authorization`, `Cookie` or `X-Org`: LiteLLM reads a key from `Authorization` too), passes the upstream status through (404, 405 and 202 are protocol answers),
  streams when the upstream answers `text/event-stream`, and ends a broken stream without an error frame. `X-Mcp-Servers: <name>,<name>` selects servers; an unknown name is a 400.
  `GET` answers 405 (no server-to-client stream: each would hold a worker thread of the pool that runs every sync route), and the relay sends the organization's key in `Authorization` too, so the master key never travels on a member's request
  (measured: `x-litellm-api-key` has priority when both are present).
  Order of side effects, from the review of #58: a Secret that is deleted or written over cannot be rolled back, so `update_server` calls the proxy first and changes Secrets after it (`_target_mode` makes the mode explicit and refuses a change on a `per_user` server that does not name it; `_apply_credential_change`),
  `delete_server` fails closed (502, everything stays) when the proxy refuses, and `remove_member` deletes the leaver's MCP credentials after the LiteLLM steps.
  `McpServer.approval` (`never`, `writes`, `always`; migration `0011`) is the admin's floor for approval in the chat playground; the backend only stores and serves it, the UI's chat route applies it.
  The mock endpoint names its tools `<alias>-echo` for each selected server, as the proxy does, because that route tells the servers apart by the prefix.
  Scopes (`utils/mcp_scope.py`, migration `0012`): organization (`owner_id` NULL), personal (`owner_id` set: the owner alone, any writer adds one) and platform (`org_id` NULL: every organization, a platform admin changes it).
  `visible(user)` is the one filter for the list, the endpoint's selection and the usage labels; `can_create`/`can_change` decide writes, so the write routes are `require_writer` plus that check; an invisible server is a 404.
  A name is unique among what its creator sees (`_name_taken`), because it selects a server on the endpoint. A platform server is registered with `allow_all_keys` (measured on v1.99.1), and the relay still names the servers of each request.
  `remove_member` also deletes the leaver's personal servers (`delete_personal_servers`).
  OAuth sign-in (`utils/mcp_oauth.py`, pure protocol: discovery, client registration, PKCE, code exchange, refresh; migration `0013`): in the data it is `per_user` with `user_auth_type = "oauth"` (`creds.is_oauth`), not a new mode, so every `per_user` branch holds.
  `McpServer.oauth` keeps the endpoints, the client id and the scopes (the client secret is a Secret, `oauth_client_secret_name`); `McpOAuthState` keeps the hash of each state with its PKCE verifier, bound to user and server, ten minutes, one use.
  The redirect URI is a page of the UI (`AIOPS_UI_URL` + `/mcp-servers/oauth/callback`), which posts `code` and `state` to `POST /v1alpha1/mcp/oauth/callback`: a callback on `/api` answers a login redirect when the session has ended, and a GET would put the code in access logs.
  The create cannot discover tools (`tools_cache = []`); the callback fills the list the first time. `creds.oauth_access_token` renews a token that ends within 60 s under one lock for each Secret, reads the Secret again inside the lock (a rotated refresh token is good once),
  and on `invalid_grant` deletes the Secret and the row, so the member reads `missing` and signs in again; a network error deletes nothing. The token cache never outlives the token.
  Every URL of the flow comes from the server or its metadata, so each passes `validate_server_url` at every use and redirects are not followed; these requests leave the backend pod, which the proxy's egress policy does not cover.
  From the review of #74: both endpoints are on the issuer's origin or on a host of `oauth.allow_hosts` (the mix-up of authorization servers: PKCE does not help when the verifier goes to the wrong token endpoint), `check_issuer` applies RFC 9207 `iss`,
  `_fetch` streams every answer under a byte cap and a deadline for the whole answer (a drip-feed held a worker thread), `expires_in` is clamped before any arithmetic (a huge integer overflows a float),
  and a Secret is written in one step, never deleted first: `KubernetesSecretStore.write` replaces, `MemorySecretStore.write` now does too, and a reader between a delete and a write found nothing and told the member to sign in. After `invalid_grant` the Secret is read a few times (`RACE_WAITS_SECONDS`) for another replica's write before the sign-in is given up,
  and after a passing failure the old token is cached for `RETRY_AFTER_SECONDS`, so calls do not queue on the same failure under the lock.
  A personal server's credential is always its owner's own (`_owners_mode`), never `shared`: the proxy keeps a shared one as `static_headers`, and any key of the organization's team could call with it.
  Names (`_name_taken`, three partial unique indexes, migration `0014`): unique among the shared servers and among one member's own; `scopes.by_name` picks the nearer server where a caller sees two.
  `delete_for_user` also deletes what a leaver stored for platform servers when this was their last membership.
  The mock (`mock_oauth_metadata`, code `mock`) points the authorization URL at the UI's own callback page. `test_mcp_oauth.py`.
  Import and deploy (ADR 0011, `docs/superpowers/specs/2026-09-20-deployed-mcp-servers-design.md`):
  `registry/mcp_registry.py` reads the official MCP registry like `huggingface.py` reads its source (`parse_server` is pure and tested against `test_fixtures/mcp_registry.json`, recorded from the real registry; `search`/`fetch` stream under a byte cap and a deadline, `fetch` needs `/v0/servers/<url-encoded name>/versions/latest`).
  A remote entry only fills the add dialog (`api/mcp_registry.py`, every writer, cached 60 s; `oauth-probe` is the hint after a refused test, one 5 s deadline, never an error, because `discover` never sees a 401: the proxy answers 200 with `error: true`).
  An image entry becomes a `draft` of `mcp_catalog` that only a platform admin sees, reviews and publishes (`api/mcp_catalog.py`); `runtimeArguments` are docker options and are refused, a loopback bind address becomes `0.0.0.0`, port and path come from the transport URL's placeholders, `latest` is refused, a secret's default is dropped, and a sync that changes what runs returns the entry to `draft`.
  The seed (`raw_data/mcp_catalog.yaml`, `load_mcp_catalog`) finds builtin rows by `(source, source_id)` and gives them `builtin_id(name)`, not a `genid` id: a seed row must not move the ids the snapshots hold.
  A deployed server is `mcp_servers` (`source = "deployed"`, created `unreachable`, because the column's default `connected` would turn it on in Chat before its pod exists) plus `mcp_instances` (migration `0015`; ORM cascade, SQLite enforces no foreign keys).
  `api/mcp_instances.py`: deploy is a plain `def` that runs Helm with `asyncio.run` in its worker thread (no `await` between a flush and its commit); names are `mcpi-<last eight hex>` (`mcp-<id8>-credentials` is taken by a shared credential; the vector database controller uses the FIRST eight, do not copy it);
  settings come from the catalog entry's schema only (`utils/mcp_catalog_settings.py`; a `flag` setting is a switch that adds an argument), secret ones live in Secret `mcpi-<id8>-env`, and a checksum of all of them rolls the pod.
  `controller/mcp_server_controller.py` has no gateway code and calls `local_chart_path` first; `utils/mcp_instances.proxy_selector` reads `AIOPS_LITELLM_NAMESPACE` and `AIOPS_LITELLM_POD_LABELS`, and without them nothing is rendered (the chart would refuse too).
  The poller `update_all_mcp_instances` has its own query (every instance that is not Stopped): `refresh_stale` leaves Running rows out, and `apply_pod_status` keeps Running while a pod restarts, so it stores `ready` and `launch` each tick.
  At first ready it registers with `server_id` = the registry row's id (`utils/mcp_registration.register_once`: a 400 "already exists" is success, measured), then the team permission, then discovery, then ONE commit (`registered_at`); a failure commits nothing and the next tick starts again; after ten minutes `last_error` names what to check.
  `utils/mcp_instances.usable` is the one answer to "does it take requests" (`ready`, registered, `connected`); `_selected` leaves such a server out (measured: one dead registered server adds 9 s to the proxy's `tools/list`) and answers 409 by name.
  The registry guards what the platform owns (PATCH of url, transport or credential: 409; refresh while not ready: 409); delete is the proxy (fail closed), then the true state committed (disabled, unregistered), then `remove_workload`, then the rows, so a delete that stops half-way can be repeated; a Failed instance is always deletable.
  An instance renders its own copy of the entry's start-up (`mcp_instances.startup`, made at deploy and at `upgrade`, which refuses a moved port or path): the proxy is registered with that port and path, and an entry that a sync returned to draft must not change a running server.
  `_register` runs the connection test BEFORE the registration (ready is a TCP check), `register_once` sends the body again on "already exists" (the allow-list is enforced in the proxy alone, and a PATCH skips the proxy while nothing is committed), and `unregister` always asks the proxy by the row's id and accepts a 404.
  `parse_server` never raises anything but `EntryError` (anybody publishes to the registry; a search leaves the entry out), the search cache has 256 keys at most and keeps no `raw`, and a setting named `LD_*`, `PATH`, `NODE_OPTIONS` or the like is refused (`LOADER_NAMES`).
  `utils/mcp_registration.py` holds the organization-based team functions and `server_body` (the old `_litellm_server`, with `server_id=`); `LiteLLMError` carries `status` and `text`.
  Mock mode: a deployed server is Starting until it is `MOCK_START_SECONDS` old, and the next read of the list or of the instance finishes it (a function of the instance alone: the fast tier is parallel); a name that starts with `failing` fails. Dev user `orgadmin` is an organization admin who is no platform admin.
  `McpUpstream` is the seam for a direct connection later. The path is excluded from the audit log by exact match (`audit/events.py` `EXCLUDED_PATHS`); each `tools/call` is an info log line.
  Token scope `mcp` (`auth/tokens.py`) is valid on that path only, with the member's role (`get_current_user` answers 403 elsewhere).
  `checked_at` and `credential_set_at` go out with the server's offset (`_aware`): the rows hold naive `datetime.now()` values, and a browser read a naive one in its own zone ("6 h" in IST for a minute-old check).
  `AIOPS_CHAT_MOCK=true` mocks discovery, registration (`litellm_server_id="mock"`) and the endpoint (a stateless JSON-RPC handler with one tool, `echo`).
  `test_mcp.py` patches `api.mcp.litellm_client`, `org_key` and `_team_id`, and `utils.mcp._resolve` so no test needs DNS.

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
- A vLLM first start downloads the weights, and the hub library does not resume after a kill, so the time allowed for it is generous on purpose:
  `controller/vllm_controller.py` renders a `startupProbe` of two hours (used by `charts/vllm` from 0.4.1 on, ignored before)
  and, for a chart without one, a liveness `initialDelaySeconds` of `VLLM_LIVENESS_INITIAL_DELAY_SECONDS` (default 7200).
  Do not shorten either without a startup probe in the published chart: on the lab a 10 GB model took 28 minutes.
- `utils/model_cache.py` reads how much of a Hugging Face model is on the shared cache volume, from the sizes of the hub library's blob files
  (`models--<org>--<name>/blobs/*`, partial `.incomplete` ones included), when the chart mounts the claim read-only into this pod (`MODEL_CACHE_DIR`, `backend.hfCache.mount`).
  `api/inference_status.py` adds it to `launch` for a `Starting` instance (`with_download`: `downloaded_bytes`, `total_bytes` from the registry's `size`, and the message).
  No exec into the engine's pod on purpose: the backend's ClusterRole has no `pods/exec`, and a progress bar is no reason to add it. Without the mount everything reads "unknown".
- `utils/pod_inspection.py` `pod_events` carries `count` and `first_at` next to `at` (the last time): Kubernetes folds a repeated event into one object, and writes none when a problem ends.
- One `check_pod_status_and_readiness(instance, db, controller=None)` signature across the three routers;
  `test_auth.py` monkeypatches it by name in `api.vectordb_instance` and `api.inference_instance`.
  `utils/kubernetes_utils.py` `PodStatus` is the only return type, there is no tuple shim.
  Its fourth field, `launch` (`LaunchProgress`), says what a not-ready instance waits for:
  a phase from a closed set (`Scheduling`, `Blocked`, `Pulling image`, `Restarting`, `Starting`, `Terminating`; `schemas/launch.py` `LaunchPhase`), a sentence, since when, `needs_attention` (only a person can move it on; the UI styles by it, never by the sentence), and the restart and replica counts,
  derived from the same pod listing (`_launch_progress`; `Failed` and `Succeeded` pods do not count, and with several pods the least advanced live pod decides), `None` when a pod serves or `failure` is set.
  `utils/instance_status.py` `apply_pod_status` puts it on the row as a plain attribute, `None` on a Stopped or Failed row, so every instance kind that calls it carries `launch`;
  the three instance schemas carry it as `launch`, and `READ_ONLY_STATUS_FIELDS` keeps a PUT from writing it.
  It is never stored and never a `status`: `test_get_does_not_persist_raw_kubelet_reasons` still holds.
  The UI shows it in `components/instances/LaunchProgress.tsx`, in a row of its own next to the Status row (the e2e page objects read that row's exact text),
  and `hooks/usePolling.ts` keeps polling while a row carries it, so a Running instance whose pod restarts is followed too.
- `api/instance_inspection.py` (`InstanceKind`, `add_inspection_routes`) is the shared logs/events/restart
  layer; `utils/pod_inspection.py` does the Kubernetes reads. `api/inference_operations.py` is stop/resume/scale
  and `PUT .../settings` on top of it
  (the instance's own `args` and `env_vars`, replaced, then one `_upgrade` shared with the replica routes: `replicaCount: 0` for a Stopped row, because a plain upgrade renders the stored `replicas` and would start it;
  each controller says what it renders (`Controller.settings_read(category)`: vLLM both, Ollama and the Hugging Face LLM chart the variables, NIM and OPEA nothing), so an edit never restarts pods for nothing,
  and the status leaf publishes it as the payload's `settingsRead`, next to `workloadChecksApiKey` and for the same reason: the UI must not guess it from the engine name;
  `utils/instance_settings.py` holds the rules both this route and create apply (422): names that are names, the names the platform owns (`VLLM_API_KEY`, `HF_TOKEN`, `HF_API_TOKEN`, `--api-key`: the charts append the user's variables after the platform's and Kubernetes takes the last),
  and one spelling for the two arguments the chart takes as `config` (`max_model_len`, `port`: whole numbers, never `--max-model-len`);
  a gateway failure commits the values, since Helm has applied them by then and a rollback would make the next stop or scale render the old ones back;
  a line break in a value once set `image` and `securityContext` on the release, so there are two defences (`test_a_value_cannot_add_keys_to_the_rendered_values`):
  `utils/render_guard.py` `refuse_line_breaks(context)` runs in front of every values template (inference, vector database, notebook) and refuses any string with a line break, whatever route stored it,
  and the engine templates write arguments, variables, `max_model_len`, `port` and the model with `| string | tojson`, never between hand-written quotes, so a quote stays inside the value;
  the generic `PUT /v1alpha1/inferenceInstance/{id}` applies `validate_settings` to its `config` too;
  `_record_window` runs on the body, so a vLLM instance keeps `max_model_len` on the row); `api/inference_status.py` is the chart lookup and status-polling leaf both of it and
  `api/inference_instance.py` import from.
- `InferenceInstanceSchema.clusterEndpoint` is the in-cluster Service URL, set on every list and detail read by
  `check_pod_status_and_readiness` (not a column, recomputed from the engine's naming rules). It is what a caller
  inside the cluster must use: the gateway's `nip.io` hosts resolve to 127.0.0.1, which inside a pod is the pod.
  It bypasses the gateway and its API-key policy. Controller mocks in tests must return a string from
  `service_url`, or response validation fails.
- `InferenceInstanceSchema.workloadChecksApiKey` is set from `Controller.workload_checks_api_key` on the same
  reads, and answers the question bypassing the gateway raises: does the workload check the credential itself?
  Only `VLLMController` sets it `True` today, because only its chart reads the credential Secret into
  `VLLM_API_KEY`; the Hugging Face, NIM and OPEA charts have no server-side key. Set it on any controller whose
  chart gains one. The UI no longer shows it (Langflow goes through LiteLLM since #29); it stays for API callers.
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
  asserts 5 jobs (three endpoint pollers, the MCP instances poller, this sync).

## Conventions and gotchas

- The default namespace is `ai-stack`, overridable with `AIOPS_NAMESPACE`; controllers read it at call time.
- Schema changes are Alembic migrations, never edits to the baseline or `create_all`:
  edit the models, `uv run alembic upgrade head` against a scratch SQLite (`DATABASE_URL=sqlite:///./tmp/dev.db`),
  then `uv run alembic revision --autogenerate -m "<message>"` and review the file
  (`env.py` uses `render_as_batch=True`, so `ALTER`s are `op.batch_alter_table()` blocks that also work on SQLite;
  drop the spurious `NUMERIC` to `UUID` `alter_column` calls SQLite reflection produces).
  Data steps go through typed `sa.table()`/`sa.column()` objects so UUID binds work on SQLite and Postgres.
  `make db-migrate` applies them to the local Postgres; `uv run alembic history` shows the chain.
- The chain is linear and `0015` (MCP servers: tables, a member's own credential, approval, scopes, OAuth, names, the deploy catalog and instances) is the single head; a new change is a new revision on top of it.
  (While the enterprise streams were open, their columns went into `0008` so that `upgrade_to_head` never saw a fork; that rule ended with their merge.)
  `test_migrations.py` checks every model agrees column for column.
- Every `HTTPException` carries a human-readable string `detail`; the frontend shows it in a toast.
  Validation errors are 422, duplicates 409, an unreachable cluster 503.
- `pyproject.toml` turns `DeprecationWarning` into errors in tests; add a targeted `filterwarnings` entry rather
  than silencing them globally.
- Ruff line length is 79; `B008` (`Depends()` defaults) and `E501` are ignored on purpose.
- `chart_values/*.yaml` are reference values for humans and are not read by the code.
- Do not commit `config.yaml` manifests; copy `manifests/config.example.yaml` and fill the secrets locally.
