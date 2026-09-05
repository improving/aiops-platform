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
Langflow used to run as a docker-compose profile on `localhost:7860`;
it now runs in the kind cluster behind the gateway
(`infra/local/langflow/langflow.yaml`), OIDC-protected the same way a
notebook or vector database route is (see "Workload access" below), but
with its own `SecurityPolicy` `langflow-oidc` rather than joining the
shared `aiops-workloads-oidc` policy -- it owns a host of its own,
`langflow.127.0.0.1.nip.io`, so it can also own a redirect URI and a
cookie suffix of its own; `https://langflow.127.0.0.1.nip.io/oauth2/callback`
is registered on the `aiops-gateway` client alongside the `sso` callback
(`infra/local/auth/realm-aiops.json`).
`make langflow-up` applies the manifests and waits for the Deployment
(first image pull is about 2 GB); `make frontend` passes
`NEXT_PUBLIC_LANGFLOW_URL` (default `LANGFLOW_URL`,
`https://langflow.127.0.0.1.nip.io`) so the page embeds it.
Without it the page shows a "Langflow is not configured" card, which is
expected.
`LANGFLOW_AUTO_LOGIN=true` stays set: the gateway is now Langflow's only
ingress, so a second login screen inside the iframe would be redundant,
not additional security (version 2 turns it off in favour of per-user
Langflow API keys, design doc section 3.4).
`make langflow-down` removes the Deployment/Service/HTTPRoute/SecurityPolicy
and keeps the PVC; `make db-down` only touches Postgres.

**Iframe caveat.** The Develop page's iframe is loaded from
`http://localhost:3000`, a different origin than
`https://langflow.127.0.0.1.nip.io`, so the OIDC session cookies the
gateway sets for the parent domain `127.0.0.1.nip.io` are sent inside
that iframe only if the browser already holds them for that domain --
i.e. only after the user has visited some `*.127.0.0.1.nip.io` host
(Langflow itself, a notebook, `auth.127.0.0.1.nip.io`, ...) at least
once in that browser and completed the Keycloak login there. On a first
visit, or in a browser that blocks third-party cookies for the iframe's
cross-site navigation, the gateway's 302 sends the frame to Keycloak's own
login page, and Keycloak sends `content-security-policy: frame-ancestors
'self'` (and `X-Frame-Options: SAMEORIGIN`) on that page -- so the browser
refuses to render the login form inside the iframe at all rather than
showing it: the frame goes blank, not to a visible login prompt (checked
with `curl -sI https://auth.127.0.0.1.nip.io/...`, see "Keycloak").
Langflow's own responses set neither header, so an *already-authenticated*
load renders normally. There is no code change for this here (frontend
files are out of scope for this task); the practical workaround is a
plain link next to or instead of the iframe, "Open Langflow" pointing at
`LANGFLOW_URL` in a new tab, so the login (and Langflow itself) can be
completed as a normal top-level navigation.

## Backend

`make backend` runs `uv run uvicorn app:app --reload` with the full local env contract:
`DATABASE_*` (the Postgres above), `AIOPS_NAMESPACE`, `AUTH_MODE` (default `oidc`) and `OIDC_ISSUER`,
the gateway env contract from "Gateway and TLS" above
(`AIOPS_PARENT_DOMAIN=127.0.0.1.nip.io`, `AIOPS_GATEWAY_NAME=aiops`, `AIOPS_GATEWAY_NAMESPACE=envoy-gateway-system`),
and `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` pointed at the local CA so it can reach Keycloak's JWKS endpoint.
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

## Tests

`docs/testing.md` covers both Playwright tiers in full:
`make ui-e2e` (fast, no cluster needed) and `make ui-e2e-cluster` (against this running stack,
logged in as alice by default) -- and how to add a scenario.
`make e2e-smoke` is the API-level smoke test;
see "How deployed instances become reachable" below for what it checks.

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
`ensure_gateway_client_secret` copies the `aiops-gateway-oidc` Secret
there and `ensure_reference_grant` adds the namespace to the two
`ReferenceGrant`s (`auth` for the `keycloak` Service, `ai-stack` for
`aiops-backend`), but the shared OIDC policy is only created in
`ai-stack`, where the `sso` callback route lives:
a browser route in any other namespace is left **unprotected** with a
warning in the backend log until a per-namespace callback host
(`sso-<namespace>`, with its own registered redirect URI) exists.
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
- **Browser routes outside `ai-stack` are unprotected.**
  The shared OIDC policy's callback host only exists in `ai-stack`;
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

