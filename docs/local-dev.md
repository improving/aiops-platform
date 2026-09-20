# Local dev stack

Runs the aiops-platform control plane (`backend/`) against a real local
Kubernetes cluster, so `backend/api/vectordb_instance.py` and
`backend/api/notebooks.py` actually install Helm charts and reconcile
`kind: Notebook` custom resources -- not mocks.

## Bring the stack up

The full local stack, in the order each piece depends on the last --
every step below has its own section further down with what it does and how to check it:

```
colima start                # if not already running; ~4 CPU / 8 GiB is enough
make kind-up                # kind cluster "aiops" + notebook-controller + ns "ai-stack"
make gateway-up              # Envoy Gateway + cert-manager + the aiops Gateway
make ca-export trust-ca      # export the local CA, print (but do not run) the trust command
make auth-up                 # Keycloak + the dev realm
make db-up                   # postgres:17-alpine on :5432
make langflow-up             # Langflow for the Develop page
make backend                 # separate terminal: FastAPI on :8000
make frontend                # separate terminal, optional: Next.js on :3000
make e2e-smoke                # exercises the backend API end to end, with a bearer token
```

`make dev` prints an older version of this sequence, from before the gateway and Keycloak existed in this stack --
follow the block above, not its output.

Tear down with `make auth-down gateway-down db-down kind-down`
(stop the `backend`/`frontend` processes yourself, e.g. Ctrl-C or `pkill -f "uvicorn app:app"`);
see "Reset everything" under Troubleshooting for the full sequence, including Langflow.

## What `make kind-up` does

1. Creates a one-node kind cluster named `aiops`
   (`infra/local/kind-config.yaml`, node image pinned to the kind v0.32.0 default).
2. Switches `kubectl`'s current context to `kind-aiops`.
3. Creates namespace `ai-stack` (idempotent).
4. Raises `fs.inotify.max_user_instances` inside the colima VM
   (see "colima inotify limit" below).
5. Installs the standalone Kubeflow notebook-controller
   (see `infra/local/notebook-controller.md` for the exact source and why).

All of this is idempotent -- re-running `make kind-up` against an existing
cluster is safe and is how you recover after `colima stop`/`colima start`.

`kind-up` also checks that an already-existing cluster has the gateway port
mappings (`infra/local/kind-config.yaml`'s `extraPortMappings`, host 80 and
443 to the node's NodePorts 30080/30443).
A cluster created before those mappings were added fails this check with a
message to run `make kind-down kind-up`; there is no way to add
`extraPortMappings` to a running kind node, so the cluster must be
recreated.

## Gateway and TLS

`make gateway-up` installs Envoy Gateway and cert-manager
(both by `helm upgrade --install`, so re-running is a no-op) and applies
the manifests in `infra/local/gateway/` (see that directory's `README.md`
for what each one does).
It waits for the `Gateway` `aiops`'s `Programmed` condition and the
`aiops-wildcard` certificate's `Ready` condition before returning, so a
clean exit means the gateway is actually serving traffic.

```
make kind-up      # cluster + the 80/443 port mappings, if not already done
make gateway-up   # Envoy Gateway + cert-manager + the aiops Gateway
make ca-export    # writes infra/local/ca/ca.crt (git-ignored)
make trust-ca     # prints, but does not run, the macOS trust command
```

Everything after `*.127.0.0.1.nip.io` resolves to `127.0.0.1` (nip.io's
wildcard DNS), which the kind port mappings forward into the cluster, so no
`/etc/hosts` editing is needed.
Check the gateway itself with:

```
kubectl -n envoy-gateway-system get gateway aiops
curl --cacert infra/local/ca/ca.crt -sI https://anything.127.0.0.1.nip.io/  # 404 from Envoy -- expected, no route matches yet
curl -sI http://anything.127.0.0.1.nip.io/                                  # also 404, plain HTTP
```

### Trusting the local CA

`infra/local/ca/ca.crt` is a throwaway CA generated fresh by cert-manager
for this cluster (`infra/local/gateway/cert-manager-ca.yaml`) -- it signs
every certificate the gateway terminates and nothing else trusts it by
default.
Two ways to make tools accept it, pick per tool:

- System-wide (macOS Keychain, works for Safari, most CLI tools):
  run the command `make trust-ca` prints yourself --
  it is intentionally not run for you, since it needs `sudo` and edits the
  System keychain.
- Per-process, via environment variables (no `sudo`, scoped to one shell):
  ```
  export SSL_CERT_FILE=$PWD/infra/local/ca/ca.crt        # stdlib ssl / openssl-based tools, curl
  export NODE_EXTRA_CA_CERTS=$PWD/infra/local/ca/ca.crt  # Node.js (frontend dev server, Playwright)
  export REQUESTS_CA_BUNDLE=$PWD/infra/local/ca/ca.crt   # python-requests does not read SSL_CERT_FILE
  ```
  Use `$PWD`, not a relative path -- Node resolves `NODE_EXTRA_CA_CERTS`
  against the process's current directory, which is not the repo root once
  `make backend`/`make frontend` have `cd`ed into `backend/`/`frontend/`.

`make gateway-down` removes the `Gateway`, the `EnvoyProxy`/`GatewayClass`,
the cert-manager `Certificate`/`ClusterIssuer` objects and both Helm
releases, but deliberately leaves the `aiops-ca` and `aiops-wildcard-tls`
secrets in place -- so the CA (and anything that already trusts it)
survives a routine `gateway-down` followed by `gateway-up`, and you don't
need to re-run `make trust-ca` after a reset.
Delete those two secrets yourself
(`aiops-ca` in `cert-manager`, `aiops-wildcard-tls` in
`envoy-gateway-system`) if you need a genuinely fresh CA.

## Keycloak

`make auth-up` runs Keycloak 26.7.3 in namespace `auth` behind the gateway
at `https://auth.127.0.0.1.nip.io/`, with the dev realm `aiops` imported
from `infra/local/auth/realm-aiops.json` -- Keycloak is the only identity
source for the stack (`docs/superpowers/plans/2026-09-04-authentication.md`).

```
make kind-up      # cluster + the 80/443 port mappings, if not already done
make gateway-up   # Envoy Gateway + cert-manager + the aiops Gateway
make auth-up      # Keycloak + the dev realm
```

`auth-up` creates the `auth` namespace, builds a ConfigMap from
`realm-aiops.json`, applies `infra/local/auth/keycloak.yaml` (the
Namespace, Service, Deployment, `HTTPRoute` and the `ReferenceGrant` that
lets a `SecurityPolicy` in `ai-stack` reference the `keycloak` Service) and
`infra/local/auth/gateway-client-secret.yaml` (the `aiops-gateway-oidc`
Secret in `ai-stack`), then restarts the Deployment and waits for it to
become `Available`, and finally creates the shared OIDC `SecurityPolicy`
`aiops-workloads-oidc` in `ai-stack` if it is missing
(`infra/local/auth/workloads-oidc-policy.yaml`, see "Workload access") --
printing the admin console URL and the dev users when it's ready. It is idempotent; re-running it is how you pick up a
realm change (see "Editing the realm" below).

### Dev users and clients

All passwords match the username.

| User | Password | Group | Email |
| --- | --- | --- | --- |
| `admin` | `admin` | `platform-admins` (role `admin`) | `admin@example.test` |
| `alice` | `alice` | `platform-members` (role `member`) | `alice@example.test` |
| `bob` | `bob` | `platform-members` (role `member`) | `bob@example.test` |

The realm role decides two things only: `admin` makes a platform admin (admin in every organization, may create organizations),
and on a user's first login it sets the role of the membership that login creates.
A user promoted in Keycloak after first login is not promoted in an organization automatically;
an organization admin changes the role on `/organization` (ADR 0008).

Clients in realm `aiops`:

- `aiops-ui` -- public, PKCE (S256), for the frontend
  (redirect URIs `http://localhost:3000/*` and `http://localhost:3001/*`).
- `aiops-gateway` -- confidential, secret `dev-gateway-secret`, for Envoy
  Gateway's shared OIDC `SecurityPolicy`
  (the one redirect URI `https://sso.127.0.0.1.nip.io/oauth2/callback`,
  see "Workload access").
- `aiops-automation` -- confidential, secret `dev-automation-secret`,
  client-credentials only (no browser flow), for `hack/e2e-smoke.sh` and
  the e2e API fixture; its service account carries realm role `member`.

Access tokens carry `realm_access.roles`, `groups` (unqualified, no leading
path), `email`/`preferred_username`/`name`, and `aud: aiops-api` from the
shared `aiops` client scope -- all four are default scopes on every client
above. `google` and `github` identity providers are present but
`enabled: false` with placeholder `REPLACE_ME` credentials.

### Verify

```
curl --cacert infra/local/ca/ca.crt -s \
  https://auth.127.0.0.1.nip.io/realms/aiops/.well-known/openid-configuration | \
  python3 -c 'import json,sys; print(json.load(sys.stdin)["issuer"])'
# https://auth.127.0.0.1.nip.io/realms/aiops

curl --cacert infra/local/ca/ca.crt -s \
  -d grant_type=client_credentials -d client_id=aiops-automation -d client_secret=dev-automation-secret \
  https://auth.127.0.0.1.nip.io/realms/aiops/protocol/openid-connect/token
# {"access_token": "...", ...} -- decode it to see aud: aiops-api, realm_access.roles: ["member"]
```

### Editing the realm

`realm-aiops.json` is only imported on Keycloak startup (`start-dev
--import-realm`), and Keycloak's dev-mode database is ephemeral (in-memory,
no volume), so there is nothing to migrate between edits -- just re-import
from scratch:

```
# edit infra/local/auth/realm-aiops.json, then:
make auth-up
```

`auth-up` re-applies the ConfigMap (picking up your edit) and restarts the
Deployment with `kubectl rollout restart`, which throws away the in-memory
database and re-imports the realm cleanly on the new pod.

A realm import is a *full* import -- unlike creating a realm through the
Admin Console, it does not seed Keycloak's built-in default client scopes
(`roles`, `profile`, `email`, `web-origins`, `basic`, `acr`) for you.
`realm-aiops.json` defines all of them explicitly (with their standard
mappers) alongside the custom `aiops` scope, specifically so that
`defaultClientScopes` references on the clients resolve instead of being
silently ignored (Keycloak logs `Referenced client scope 'X' doesn't exist.
Ignoring` for each one it drops) -- if you add a new default client scope
reference, either use one of these or define it too.

`make auth-down` deletes the `auth` namespace (Keycloak and everything in
it) and the `aiops-gateway-oidc` Secret from `ai-stack`.

## Postgres

`make db-up` starts `postgres:17-alpine` in docker compose on `localhost:5432`
(`infra/local/docker-compose.yml`, container `aiops-local-postgres`, user/password/database all `postgres`)
and waits for its healthcheck;
`make db-down` stops it and keeps the data volume.
`make backend` runs the Alembic migrations against it automatically on startup
(`db/migrate.py::upgrade_to_head`, creating the `default` organization the first time);
apply the same migrations without starting the API with `make db-migrate`.

## Langflow for the Develop page

The Develop page embeds Langflow.
Langflow runs in the kind cluster behind the gateway
(`infra/local/langflow/langflow.yaml`), on platform identity (ADR 0002,
design `docs/superpowers/specs/2026-09-08-langflow-native-identity-design.md`):
the gateway logs the browser in against Keycloak,
asks the backend whether this member may open Langflow (ext-authz, the `langflow` host rule),
and forwards the access token;
Langflow verifies that token itself (`LANGFLOW_EXTERNAL_AUTH_*`)
and keeps one Langflow user per platform user, named after the Keycloak username.
So `GET https://langflow.127.0.0.1.nip.io/api/v1/users/whoami` names the person who is signed in,
there is no second login screen, and flows are personal: they follow the person, not the organization.
Langflow has its own `SecurityPolicy` `langflow-oidc` rather than joining the shared
`aiops-workloads-oidc` policy, because it owns a host of its own and so can own a redirect URI
(`https://langflow.127.0.0.1.nip.io/oauth2/callback` is registered on the `aiops-gateway` client
alongside the `sso` callback, `infra/local/auth/realm-aiops.json`).

`make langflow-up` does three things, all idempotent:
it generates the break-glass superuser Secret `langflow-superuser` (`aiops-admin`, a random password, never printed) once;
it publishes `infra/local/ca/ca.crt` as the ConfigMap `aiops-ca` and substitutes the gateway's ClusterIP into the manifest,
because Langflow accepts an https JWKS URL only and the pod therefore fetches the realm's keys from
`https://auth.127.0.0.1.nip.io` through the gateway, trusting the local CA;
and it applies the manifest and waits for the rollout (the first image pull is about 2 GB).
A Langflow volume from before the switch still holds the shared user `langflow`:
run `make langflow-retire-shared-user` once to deactivate it through Langflow's API
(`infra/local/langflow/retire-shared-user.py`, run inside the pod as the superuser; its flows are kept).
Flows reach models through LiteLLM and tools through the backend's MCP endpoint, and nothing else in the cluster,
so the pod's `LANGFLOW_SSRF_ALLOWED_HOSTS` names `litellm.litellm.svc` and `aiops-backend.ai-stack.svc`
(the selector-less Service of `make gateway-up` that points at the backend on the laptop).
`make backend` sets `AIOPS_BACKEND_CLUSTER_URL` to that Service, and the Develop page then writes `AIOPS_MCP_URL` and `AIOPS_MCP_TOKEN` into the member's Langflow variables.
`make mcp-test-up` deploys a small MCP server in kind (`echo`, `whoami`, any bearer) to register on the MCP servers page:
`http://mcp-test.mcp-test.svc.cluster.local:8000/mcp`, a host `make backend` allows although the URL rule refuses cluster addresses.
`make frontend` passes `NEXT_PUBLIC_LANGFLOW_URL` (default `LANGFLOW_URL`, `https://langflow.127.0.0.1.nip.io`)
so the page embeds it; without it the page shows a "Langflow is not configured" card, which is expected.
`make langflow-down` removes the Deployment/Service/HTTPRoute/SecurityPolicy
and keeps the PVC and the superuser Secret; `make db-down` only touches Postgres.

After every change to `langflow-oidc`, check that the controller accepted it:

```bash
kubectl -n ai-stack get securitypolicy langflow-oidc -o jsonpath='{.status.ancestors[0].conditions[0]}'
```

A rejected `SecurityPolicy` is not applied at all, and its route is then open, with no login and no ext-authz
(measured: `passThroughAuthHeader` without a `jwt` block was rejected, and the host answered 200 to a request with no session).

**The switch to platform identity, once.**
Before 2026-09-08 every browser was the one auto-login superuser `langflow`.
That user is deactivated, not deleted; its one flow and its variables are still in the database.
To recover them, sign in as the break-glass superuser through a port-forward
(nothing on the gateway host accepts a password login):

```bash
kubectl -n ai-stack port-forward deploy/langflow 7860
pw=$(kubectl -n ai-stack get secret langflow-superuser -o jsonpath='{.data.password}' | base64 -d)
tok=$(curl -s -d "username=aiops-admin" -d "password=$pw" http://localhost:7860/api/v1/login | jq -r .access_token)
id=$(curl -s -H "Authorization: Bearer $tok" 'http://localhost:7860/api/v1/users/?limit=100' | jq -r '.users[] | select(.username=="langflow") | .id')
curl -s -X PATCH -H "Authorization: Bearer $tok" -H 'content-type: application/json' -d '{"is_active": true}' http://localhost:7860/api/v1/users/$id
curl -s -X PATCH -H "Authorization: Bearer $tok" -H 'content-type: application/json' -d '{"password": "<a new one>"}' http://localhost:7860/api/v1/users/$id/reset-password
```

then sign in as `langflow` on `http://localhost:7860`, export the flow, and deactivate the user again.
A browser that opened Langflow before the switch still holds Langflow's own cookies for the shared user;
they are harmless: the bundle sends the stale token, Envoy refuses it, the bundle drops its cookies
and comes back through the gateway login (pinned by `e2e/cluster/langflow-authz.spec.ts`).

**Calling Langflow's API.** `passThroughAuthHeader` is on, so a request carrying a Keycloak access token
skips the gateway login and reaches Langflow as that person:

```bash
curl --cacert infra/local/ca/ca.crt -H "Authorization: Bearer $KEYCLOAK_ACCESS_TOKEN" https://langflow.127.0.0.1.nip.io/api/v1/users/whoami
```

A client-credentials token (`aiops-automation`) and a personal `aiops_…` token are refused by the control plane with
`Langflow opens for signed-in members only, not for service accounts or personal tokens`;
a bearer that is not a realm token is refused by Envoy's own JWT check.
The backend uses this path to provision a member's Langflow account (`utils/langflow.py`).

**Iframe caveat.** The Develop page's iframe is loaded from
`http://localhost:3000`, a different origin than
`https://langflow.127.0.0.1.nip.io`, so the OIDC session cookies the
gateway sets for the parent domain `127.0.0.1.nip.io` are sent inside
that iframe only if the browser already holds them for that domain --
i.e. only after the user has visited some `*.127.0.0.1.nip.io` host
(Langflow itself, a notebook, `auth.127.0.0.1.nip.io`, ...) at least
once in that browser and completed the Keycloak login there. On a first
visit, or once that session has expired, the gateway's 302 sends the
frame to Keycloak's own login page, and Keycloak sends `content-security-policy: frame-ancestors
'self'` (and `X-Frame-Options: SAMEORIGIN`) on that page -- so the browser
refuses to render the login form inside the iframe at all rather than
showing it: the frame goes blank, not to a visible login prompt (checked
with `curl -sI https://auth.127.0.0.1.nip.io/...`, see "Keycloak").
Langflow's own responses set neither header, so an *already-authenticated*
load renders normally. The page says so and offers "open Langflow in a new tab":
completing the login as a top-level navigation is the way back.
The gateway's OIDC cookies are `SameSite=None` with `Secure`, so an authenticated browser's frame does
authenticate on its own.

## LiteLLM

`make litellm-up` runs the LiteLLM proxy (official Helm chart, `infra/local/litellm/values.yaml`) in namespace `litellm`,
against a `litellm` database on the compose Postgres (the target creates it; pods reach the host as `192.168.5.2`),
and publishes it through the gateway at `https://litellm.127.0.0.1.nip.io` with no gateway policy:
LiteLLM authenticates every call with its master key (`sk-dev-litellm-master`, a dev-only literal) or a virtual key.
The target is idempotent; the `litellm-env` Secret with the salt key is created once and never rewritten,
because the salt encrypts the provider keys LiteLLM stores.
`make backend` passes `LITELLM_URL` and `LITELLM_MASTER_KEY` to the API;
without them every LiteLLM call in the backend is a no-op, the way `AIOPS_PARENT_DOMAIN` gates the gateway.

What the platform does with it:
every deployed inference instance is registered as LiteLLM model `inst-<id8>` with its in-cluster Service URL and workload credential,
each organization gets a LiteLLM team and one virtual key (Secret `org-<id8>-litellm-key` in the platform namespace),
and `POST /v1alpha1/chat/completions`, `/embeddings` and `/rerank` forward to LiteLLM with that key,
so spend and the Prometheus metrics at `/metrics/` (trailing slash; master key) are labelled per organization.
`infra/local/litellm/README.md` lists the Secrets and the useful calls.

## Hosted providers

An organization admin adds a hosted provider on `/providers` (OpenAI, Anthropic, Google Gemini, Groq, OpenRouter):
kind, a name, an optional base URL and the API key.
The key goes into the Secret `prov-<id8>-credentials` in the platform namespace (never into the database or a response),
"Discover models" lists what the key can reach (`POST /v1alpha1/providers/discover`),
and every picked model is registered in LiteLLM as `prov-<id8>/<model>` with that key,
so it appears as a hosted chat target next to the deployed instances.
Context length and prices come from LiteLLM's public prices file (`backend/utils/model_prices.py`).
The same page shows the organization's spend and lets an admin set a monthly budget
(`PUT /v1alpha1/organizations/current/budget`, a LiteLLM team budget; empty means no cap).
The fast Playwright tier exercises the page with a mock discovery and an in-memory secret store
(`AIOPS_CHAT_MOCK=true`, `AIOPS_SECRET_STORE=memory`, both honoured only with `TEST_MODE=true`);
a real hosted chat runs only when `E2E_OPENAI_API_KEY` is set in the shell for `hosted-chat.spec.ts`
(the key is never written to a file).

## Model registry

The catalog is a registry in the database, seeded from `backend/raw_data/models.yaml` on an empty database
and managed by admins on `/models/registry`:
list with filters (source, capability, status), publish or deprecate, edit, sync, delete,
"Import from Hugging Face" (search, preview, import as draft), "Add Ollama model" (a tag, sized from the registry manifest),
"Add hosted model" (a model from an enabled OpenRouter provider) and "Add manually".
Members see published entries in the catalog; the launch wizard offers an entry's serving options
(engine plus reference, for example `Ollama` with `hf.co/Qwen/Qwen3-0.6B-GGUF:Q8_0` for a GGUF repo)
and the instance keeps the chosen `reference`.
Published entries with a source are re-synced daily (`REGISTRY_SYNC_INTERVAL_SECONDS`, `0` disables), best effort.

`make registry-export` writes the registry of the local Postgres back to `backend/raw_data/models.yaml`
(global entries only, stable order), so catalog changes travel through pull requests;
the file must equal the export of a database seeded from it.
The Playwright fast tier and the backend tests never call the sources:
`AIOPS_CHAT_MOCK=true` makes the importers read the recorded fixtures under `backend/test_fixtures/`.

## Usage and metrics

Every chat, embeddings and rerank request the backend forwards to LiteLLM carries the platform user id as the OpenAI `user` field
(an opaque id, so no email reaches LiteLLM's database, its metrics or an upstream provider;
the Usage page maps ids back to emails, the Grafana dashboard's `end_user` filter shows the ids),
so LiteLLM's spend logs and its Prometheus metrics attribute tokens and spend to the user, the target and the organization's team.
The Usage page (`/usage`, header link "Usage") reads `GET /v1alpha1/organizations/current/usage?days=30`:
members see their own rows, admins the whole organization, with totals, a table per target and a table per user and day.
Chat, embeddings and rerank name the platform user on each request;
a Langflow flow calls LiteLLM directly and names nobody, so each member's Langflow account gets a LiteLLM key of their own
(same team and budget as the organization's, owned by their user id), and the page attributes those rows to the key's owner.
Rows with neither appear to admins as unattributed: requests made before the attribution landed, with the master key,
or by a Langflow account that still holds the organization's key (it gets the member's key on their next visit to the Develop page).

`make monitoring-up` installs kube-prometheus-stack in namespace `monitoring`
(Prometheus with a 2-day retention, the operator, kube-state-metrics and Grafana; no alertmanager, no node exporter, small requests
so one Ollama instance still fits on the 8 GiB VM),
publishes Grafana at `https://grafana.127.0.0.1.nip.io` through the gateway,
scrapes LiteLLM's `/metrics/` with a `ServiceMonitor` that carries the master key,
and installs `charts/infracloud-dashboards`, which now includes the LiteLLM dashboard (uid `aiops-litellm`):
requests, input and output tokens per second, time to first token, request latency, failed requests, spend and tokens by user,
filtered by target (`inst-<id8>`, `prov-<id8>/<model>`) and user.
Grafana here is dev-only: anonymous viewers, embedding allowed, no gateway policy, admin password `admin`.
`make frontend` sets `NEXT_PUBLIC_GRAFANA_URL`, so an Ollama instance's Dashboards tab embeds those panels
(the rows come from `backend/raw_data/engine_chart_dashboards.csv`, and every instance's panel URL carries `var-target`);
with monitoring down the tab shows failing frames instead of the "not configured" card,
and the browser must trust the local CA (`make trust-ca`) for the frames to load.
The TGI, TEI and vLLM dashboards keep working on the lab, where those engines expose their own metrics.

## Backend

`make backend` runs `uv run uvicorn app:app --reload` with the full local env contract:
`DATABASE_*` (the Postgres above), `AIOPS_NAMESPACE`, `AUTH_MODE` (default `oidc`) and `OIDC_ISSUER`,
the gateway env contract from "Gateway and TLS" above
(`AIOPS_PARENT_DOMAIN=127.0.0.1.nip.io`, `AIOPS_GATEWAY_NAME=aiops`, `AIOPS_GATEWAY_NAMESPACE=envoy-gateway-system`),
and `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` pointed at `infra/local/ca/bundle.crt`,
which `make backend` builds from certifi's public roots plus the local CA,
so the process reaches Keycloak's JWKS endpoint and the gateway hosts as well as public hosts
(provider discovery at api.openai.com, the Hugging Face Hub, chart repositories).
Calls to public hosts in the code also pass certifi explicitly (`backend/utils/tls.py`),
so a plain `SSL_CERT_FILE=infra/local/ca/ca.crt` still works for them.
It also sets `AIOPS_CHARTS_DIR=$(PWD)/charts`:
a chart that exists there (`charts/<chart_name>/Chart.yaml`) is installed from the checkout
instead of the published index, so a chart change can be tried before it is released.
Without `AIOPS_PARENT_DOMAIN` set (a plain `uv run uvicorn`),
no `HTTPRoute`s or `SecurityPolicy`s are created for deployed instances
and their endpoint falls back to the `ClusterIP` --
see "How deployed instances become reachable" below.
`AUTH_MODE=disabled` is a backend-only bypass for single tests and the fast Playwright tier,
and only takes effect together with `TEST_MODE=true`;
`make backend` never sets either.

## Frontend

`make frontend` runs `pnpm dev` with `AUTH_MODE`/`NEXT_PUBLIC_AUTH_MODE` (default `oidc`),
`AUTH_SECRET`, `AUTH_URL=http://localhost:3000`, `AUTH_KEYCLOAK_ISSUER`, `AUTH_KEYCLOAK_ID=aiops-ui`,
`NEXT_PUBLIC_LANGFLOW_URL` and `NODE_EXTRA_CA_CERTS` pointed at the local CA
(`frontend/.env.example` documents the same variables for running `pnpm dev` directly, outside `make frontend`).
Opening `http://localhost:3000` redirects to `/login`;
"Sign in with Keycloak" starts the same OIDC code flow a deployed workload's gateway route uses,
and any of the three dev users can sign in (see "Dev users and clients" under Keycloak).
`AUTH_MODE=disabled` skips the login redirect and the bearer header entirely
and is meant only for the fast Playwright tier.

## Chat with a small model on Ollama

Ollama is an inference engine like the others, but it runs on CPU,
so it is the one engine that works on the kind stack.
The catalog carries three Apache 2.0 Ollama tags
(`qwen3:0.6b`, `qwen2.5:1.5b-instruct`, `smollm2:1.7b`; `backend/raw_data/models.yaml`);
launching one from the catalog offers only the Ollama engine,
and the accelerator step can be skipped with Next (no GPU host needed).
The first launch pulls the Ollama image (about 2.6 GiB) and the model (0.5 to 1.8 GiB) onto the kind node,
so the instance takes 5 to 10 minutes to become Ready the first time;
the chart's `postStart` hook pulls the model before the pod reports Ready
and re-creates it in place with the chart's `ollama.contextLength` (4096):
a model's own `num_ctx` (Hugging Face GGUF repos ship 40960) would otherwise override `OLLAMA_CONTEXT_LENGTH`,
and its KV cache alone (about 4.4 GiB) exceeds the pod's memory limit, so the first chat OOM-kills the container.
The instance gets the usual `inf-<id8>` gateway host with an API key.
That host answers `401 Client authentication failed.` to a browser,
because only requests with the key in `x-api-key` pass the gateway,
and Ollama has no `/docs` page either:
use the Chat page, or an OpenAI-compatible client pointed at `<endpoint>/v1` with the key.

`/chat` (the "Chat" header link, or the "Chat" button on an endpoint page) talks to a Ready instance:
the browser posts to the UI's own `/api/chat` route handler (Vercel AI SDK),
which calls the backend's `POST /v1alpha1/chat/completions` with the session's bearer token
and `model` set to the target name (`inst-<id8>`, from `GET /v1alpha1/chat/targets`);
the backend forwards the OpenAI-compatible request to LiteLLM with the organization's virtual key
(or, without LiteLLM, to the instance's gateway host with its workload credential)
and streams the answer back.
Conversations stay in the browser (`localStorage`, one per instance) and are never stored server-side.

To talk to an instance from a terminal, use the same endpoint with the automation token
(`hack/e2e-smoke.sh` does exactly this):

```bash
curl -sN localhost:8000/v1alpha1/chat/completions \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"model":"inst-<id8>","messages":[{"role":"user","content":"hello"}],"stream":true}'
curl -s localhost:8000/v1alpha1/embeddings \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"model":"inst-<id8 of an embedding instance>","input":["hello world"]}'
```

Memory: the chart requests 1 CPU and 2 GiB and limits memory to 4 GiB
(`backend/templates/ollama-llm-values.yaml.jinja`, `charts/ollama/values.yaml`);
one small model fits next to Keycloak, the gateway, Langflow and LiteLLM on the 8 GiB colima VM,
and a second Ollama instance stays `Pending` with "Insufficient memory" until the first is deleted
(the smoke test and the cluster tier therefore launch instances one after the other).
Check with `kubectl describe node aiops-control-plane` ("Allocated resources") or `docker stats aiops-control-plane`.

## The platform chart on kind

`make chart-images chart-smoke` installs `charts/aiops-platform` next to the dev stack:
namespace `aiops-platform`, parent domain `platform.127.0.0.1.nip.io`, the dev `Gateway` `aiops` reused,
its own certificate for `*.platform.127.0.0.1.nip.io` from the dev CA added to the Gateway's https listener,
and the dev users imported into the bundled Keycloak.
`docs/install.md` explains the chart; this is only the local recipe.
Delete a running Ollama instance first (memory), trust the CA for the browser (`make trust-ca`),
then open `https://ui.platform.127.0.0.1.nip.io/` and sign in as `alice`.
`make chart-uninstall` removes the namespace and the certificate again.
The chart-installed backend attaches `nb-`/`vdb-` browser routes to the `aiops-workloads-oidc` policy the chart renders in its own namespace
(see "Other namespaces" under "Workload access").

## Tests

`docs/testing.md` covers both Playwright tiers in full:
`make ui-e2e` (fast, no cluster needed) and `make ui-e2e-cluster` (against this running stack,
logged in as alice by default) -- and how to add a scenario.
`make e2e-smoke` is the API-level smoke test;
see "How deployed instances become reachable" below for what it checks.
It also launches `qwen3:0.6b` on Ollama, waits for Ready and asks for one chat completion
(`ARGS="--skip-ollama"` skips that part, `--skip-notebook` the notebook part).

## How deployed instances become reachable

Every instance the backend deploys (notebooks, vector databases, inference
endpoints) gets a Service of type `ClusterIP` -- kind does not ship a
cloud-controller-manager, so a `LoadBalancer` Service would stay `Pending`
forever, and nothing needs one.
Instead, once the backend has the gateway env contract
(`AIOPS_PARENT_DOMAIN`, `AIOPS_GATEWAY_NAME`, `AIOPS_GATEWAY_NAMESPACE` --
`make backend` sets all three), each controller creates one or two
`HTTPRoute`s per instance (`backend/utils/gateway.py`) under a deterministic
hostname:

```
nb-<id8>.127.0.0.1.nip.io          # notebooks (browser)
vdb-<id8>.127.0.0.1.nip.io         # vector databases (browser)
vdb-<id8>-api.127.0.0.1.nip.io     # vector databases (SDK, API key)
inf-<id8>.127.0.0.1.nip.io         # inference endpoints (SDK, API key)
```

`<id8>` is the *last* eight hex characters of the instance id (see
`backend/utils/gateway.py::id8`), not the first eight the Helm release name
uses.
Inference has no browser UI, so it gets a single SDK route (`inf-<id8>`)
and no `-api` twin.
The backend stores these gateway URLs as the instance's `endpoint` (and, for
vector databases, `api_endpoint`) as soon as the gateway is configured --
deterministically, without waiting for the Service to exist -- so
`hack/e2e-smoke.sh` and the Playwright cluster tier curl them directly with
`--cacert infra/local/ca/ca.crt` / `ignoreHTTPSErrors` instead of
port-forwarding.

Without `AIOPS_PARENT_DOMAIN` set (for example, in the fast Playwright tier
or a plain `uv run uvicorn`), no `HTTPRoute`s are created and `endpoint`
falls back to the Service's `ClusterIP`, exactly as before the gateway
existed -- see `backend/utils/kubernetes_utils.py::get_service_endpoint`.
`make lb` and `cloud-provider-kind` are no longer part of this path;
they remain useful only if you want a real `LoadBalancer` IP for some
other, unrelated Service.

### Timeouts

Envoy's default route timeout is 15 seconds, which cuts a streamed answer that takes longer
(a cold model loading, a long generation) with "peer closed connection" in the backend and a broken stream in the chat.
Routes that stream get a `BackendTrafficPolicy` with no request timeout and a 10-minute idle timeout:
the LiteLLM route (`infra/local/litellm/gateway.yaml`) and every `inf-<id8>` route the backend creates
(`INFERENCE_TIMEOUTS` in `backend/utils/gateway.py`); notebook routes keep their one-hour WebSocket policy.
When a stream still breaks, the backend ends it with an OpenAI-style error event and the chat page shows the reason with a Retry button.

## Workload access

Every route above is protected at the gateway
(`docs/superpowers/plans/2026-09-04-authentication.md`, Task 10);
the objects are Envoy Gateway `SecurityPolicy`s that the controllers
create next to the `HTTPRoute`s, through `backend/utils/gateway.py`.

| Host | Who may use it | Gateway check |
| --- | --- | --- |
| `nb-<id8>` | the notebook's owner, or an org admin | OIDC login, then ext-authz |
| `vdb-<id8>` | any member of the organization | OIDC login, then ext-authz |
| `vdb-<id8>-api` | anyone with the instance's API key | `apiKeyAuth` (the credential store issues the key) |
| `inf-<id8>` | anyone with the instance's API key | `apiKeyAuth` (the credential store issues the key) |

### Browser hosts: one shared OIDC policy

Browser hosts share **one** `SecurityPolicy`, `aiops-workloads-oidc` in
`ai-stack` (`infra/local/auth/workloads-oidc-policy.yaml`), whose
`targetRefs` list the controllers maintain:
creating a notebook or a vector database adds its browser route
(`add_oidc_target`), deleting it removes the route again
(`remove_oidc_target`);
the backend also creates the policy itself when it is missing.
It is one policy and not one per instance because of two facts found in
the Task 10 spike (gateway notes, "Spike results"):
Keycloak does not glob-match a `*` in the host of a redirect URI,
and Envoy Gateway names its OIDC cookies with a suffix derived from the
policy, so only the policy that started a login can finish it.
Hence every login ends on the shared callback host
`sso.127.0.0.1.nip.io` (`infra/local/gateway/sso.yaml`,
a tiny nginx behind an `HTTPRoute` that is the policy's first target),
`https://sso.127.0.0.1.nip.io/oauth2/callback` is the only redirect URI
registered on the `aiops-gateway` client,
and the cookies are set for the whole parent domain (`cookieDomain`),
so one login covers every instance host.

What a request goes through, in order
(`infra/local/gateway/envoyproxy.yaml` moves the OIDC filter ahead of
ext-authz):

1. No session cookie: 302 to Keycloak, login, 302 back to `sso`,
   code exchange, cookies set, 302 to the host you started on.
2. ext-authz: Envoy calls the API at
   `http://aiops-backend.ai-stack:8000/v1alpha1/authz/route` with the
   original `Host`, method, path, `Authorization` (the access token,
   `forwardAccessToken: true`) and `Cookie` headers
   (`backend/api/authz.py`, `failOpen: false`).
   The API answers 200 with `X-Auth-User-Email`, `X-Auth-User-Sub` and
   `X-Auth-Org`, which Envoy copies to the workload, or 403.
3. The workload.

`aiops-backend` is a selector-less Service plus an `EndpointSlice`
(`infra/local/gateway/backend-host-service.yaml`) pointing at the Mac,
because the API runs on the host with `make backend`.
`make gateway-up` resolves the address with
`docker exec aiops-control-plane getent hosts host.docker.internal`
(`192.168.5.2` under colima);
if that lookup fails, pass the address yourself:
`make gateway-up HOST_IP=<the Mac as seen from the kind node>`.
Check it from inside the cluster with

```
kubectl -n ai-stack run curl --rm -i --restart=Never --image=curlimages/curl:8.10.1 -- \
  -s http://aiops-backend.ai-stack:8000/health   # {"message":"OK"}
```

Notebook routes also get a `BackendTrafficPolicy` with the same name
(`requestTimeout: 0s`, `streamIdleTimeout: 1h`) so kernel WebSockets
survive longer than Envoy's default five-minute idle timeout.
The notebook Service carries no `appProtocol: kubernetes.io/ws`:
the notebook-controller rewrites the Service ports on every reconcile,
so a patch is undone within seconds, and Envoy speaks HTTP/1.1 to a
Service without `appProtocol`, which is all a WebSocket upgrade needs
(verified: a kernel ran cells through the gateway, gateway notes
"Spike results").

### SDK hosts: one API-key policy per route

`vdb-<id8>-api` and `inf-<id8>` each get their own `SecurityPolicy`,
named after the route, with `apiKeyAuth` reading the key from the
`x-api-key` or `api-key` header and the Secret `<kind>-<id8>-apikey-auth`.
The credential store (`backend/utils/credentials.py`) writes that Secret before the instance is installed,
and the policy is created right after it,
so every vector database and every inference endpoint gets one from the start
(only vLLM also enforces the same key server-side; the others rely on the gateway alone);
only a route created without a gateway configured
(see "How deployed instances become reachable") has no policy at all.

### Other namespaces

`AIOPS_NAMESPACE` may point the controllers at another namespace.
A `SecurityPolicy` can only target routes in its own namespace,
so `add_oidc_target` patches the `aiops-workloads-oidc` policy of the
route's namespace: the one `make auth-up` created in `ai-stack`,
or the one the umbrella chart renders in its release namespace.
`ensure_gateway_client_secret` copies the `aiops-gateway-oidc` Secret
there and `ensure_reference_grant` adds the namespace to the two
`ReferenceGrant`s (`auth` for the `keycloak` Service, `ai-stack` for
`aiops-backend`);
when the policy is missing it is built from scratch only if an `sso`
callback route exists in that namespace (nothing else could complete a
login), otherwise the browser route cannot be protected.
That case **fails closed**: the route is deleted again, the install
fails and the row is `Failed` with the policy named in the reason;
a workload is never left reachable without a login.
API-key policies work in any namespace.

### Check it

```
curl --cacert infra/local/ca/ca.crt -sI https://nb-<id8>.127.0.0.1.nip.io/   # 302 to auth.127.0.0.1.nip.io
kubectl -n ai-stack get securitypolicy,backendtrafficpolicy               # aiops-workloads-oidc plus one BTP per notebook
kubectl -n ai-stack get securitypolicy aiops-workloads-oidc -o jsonpath='{.spec.targetRefs[*].name}'
grep "api.authz" <backend log>                                           # one line per decision, with the Host Envoy sent
```

A `make auth-up` re-import keeps the policy's `targetRefs`
(it only creates the policy when it is missing) but restarts Keycloak,
which ends every session: log in again.

## Known limitations

- **Keycloak sessions do not survive a restart.**
  `start-dev` keeps its database in memory (see "Editing the realm" above);
  any restart of the Keycloak pod -- a `make auth-up` re-import, a crash, `kubectl delete pod` --
  invalidates every session and refresh token,
  and every signed-in user (UI and gateway alike) has to log in again.
  The identity spike hit this directly:
  a Keycloak pod replaced between a login and a scheduled token refresh
  turned a working session into `invalid_token: Invalid refresh token` (identity notes, "Spike results").
- **The Develop page's Langflow iframe needs a prior login on the gateway domain.**
  See "Iframe caveat" under "Langflow for the Develop page" above.
- **A namespace without the shared OIDC policy cannot run notebooks or vector databases.**
  Their browser routes must join `aiops-workloads-oidc` in that namespace, or the launch fails;
  see "Other namespaces" under "Workload access" above.
- **The Qdrant dashboard needs its API key pasted in by hand.**
  The `vdb-<id8>` browser host only checks the OIDC login and ownership (ext-authz) --
  it does not inject the instance's workload credential into the request.
  Qdrant itself is configured with that same key as its `apiKey`
  (`backend/templates/qdrant-values.yaml.jinja`),
  so it rejects every REST call the dashboard's own JavaScript makes,
  including from an already-authenticated browser,
  until the value from `GET /v1alpha1/credentials/vdb/<id>` (or the UI's "Show credential" dialog)
  is pasted into the dashboard's own "API key" field.
  That is Qdrant enforcing its own auth on top of the gateway's, not a bug here.

## Troubleshooting

### Reset everything

Tear down every piece this doc brings up, without touching colima or kind itself:

```
make auth-down        # Keycloak, the dev realm, the ai-stack client secret and the shared OIDC policy
make langflow-down     # Langflow (keeps the PVC)
make gateway-down       # Envoy Gateway + cert-manager (keeps the CA secrets, see "Trusting the local CA")
make db-down             # Postgres (keeps the data volume)
```

Then bring it back up from "Bring the stack up" above.
Because `gateway-down` deliberately leaves `aiops-ca`/`aiops-wildcard-tls` in place,
a fresh `make gateway-up` reuses the same CA and you do not need to re-run `make trust-ca`.
Add `make kind-down` as well only if you also want a fresh cluster
(see "Start over from scratch" below for the colima-level wipe).

### Start over from scratch

`colima delete` keeps the container runtime data on a separate disk
(`~/.colima/_lima/_disks`), so images, volumes and the kind cluster survive it.
To wipe everything and rebuild:

```
make kind-down          # optional, the VM goes anyway
colima stop
colima delete --data    # removes the VM and the data disk
colima start --cpu 4 --memory 8 --disk 60
make kind-up
make db-up
```

### colima not running

`colima status` reports `colima is not running`.
Run `colima start`. `make kind-up` and `make prereqs` both check for this
and warn, but do not start it for you.

### colima inotify limit / notebook-controller crash-loops

Symptom: `kubectl -n notebook-controller-system logs deploy/notebook-controller-deployment`
shows `failed to create fsnotify watcher: too many open files` and the pod
restarts repeatedly.

Cause: the default colima Lima VM ships `fs.inotify.max_user_instances=128`,
which kubelet + containerd + the controller-runtime manager exhaust between
them. `make kind-up` raises it to 8192 every time it runs, but the setting
does not persist across `colima stop`/`colima start` -- just re-run
`make kind-up` (it is idempotent, including this step).

### Image pulls are slow

The Jupyter notebook images (`kubeflownotebookswg/jupyter-*-full`) are
several GB. First pull inside the kind node can take minutes depending on
your network. Accelerate it by pre-pulling on the host and loading it
straight into the kind node's containerd, skipping the pull entirely for
that image:

```
docker pull kubeflownotebookswg/jupyter-pytorch-full:v1.9.2
kind load docker-image kubeflownotebookswg/jupyter-pytorch-full:v1.9.2 --name aiops
```

(If `kind load docker-image` errors with a content-digest mismatch on a
multi-arch image, it's a known kind/containerd quirk with `--all-platforms`
import -- the pod will still pull the image directly from the registry via
containerd inside the node, which works, just without the local-load
shortcut.)

### Notebook instances stay Pending with "Insufficient nvidia.com/gpu"

The `kf-notebooks` chart defaults `notebooks.jupyter.resources.limits."nvidia.com/gpu"` to `"1"`.
`backend/templates/kf-notebooks-values.yaml.jinja` sets that key to `null` when `nvidia_gpu` is false,
which removes it on the Helm merge, so a GPU-less notebook schedules on kind.
If you see this event again, check the rendered values with
`helm -n ai-stack get values <release>`:
the `nvidia.com/gpu` key must be absent or null.
`--skip-notebook` skips the notebook part of the smoke test when you only want the vector DB path.

### Notebook CRD missing

Symptom: creating a notebook instance 500s with a Helm error mentioning
`Notebook CRD is not installed in the cluster`.
Run `make kind-up` again -- it installs the CRD as part of the
notebook-controller install -- and confirm with:

```
kubectl get crd notebooks.kubeflow.org
```

### The dev server answers "Page not found" for a new route

A `next dev` that was started before a new `src/app/<route>/page.tsx` existed
(for example after a `git checkout` or a cherry-pick that added the file)
can keep answering 404 for that route while every existing page still works.
Restart `make frontend`; the built UI of the fast Playwright tier is not affected.

### Seeing what's actually running

```
helm -n ai-stack list                       # Helm releases the backend created
kubectl -n ai-stack get pods,svc,notebooks  # workloads + the Notebook CRs
kubectl -n notebook-controller-system get pods,deploy
```

### Helm installs take minutes the first time

The first `POST /v1alpha1/vectordb_instances` or `/v1alpha1/notebooks` in a
fresh session takes 2-3 minutes even though the pod itself starts in
seconds -- `backend/controller/vectordb_controller.py` and
`notebooks_controller.py` call `helm.get_chart(..., repo=...)` /
`install_or_upgrade_release(...)` with a bare `--repo` URL rather than a
named local repo, so Helm re-fetches the repo index over the network on
every install.
Once Helm's local chart cache is warm (after the first install of a given
chart+version), subsequent installs are fast (seconds, confirmed by
re-running `hack/e2e-smoke.sh`: 176s cold vs. 25s warm for the same Qdrant
install).
This is expected Helm/pyhelm3 behavior, not a bug --
just budget for it the first time you run the stack.

