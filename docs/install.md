# Install the platform with Helm

`charts/aiops-platform` installs the control plane on a Kubernetes cluster:
the backend API, the UI, the gateway objects,
and Postgres, Keycloak and LiteLLM as dependencies that can each be replaced by an external system.
The raw manifests under `infra/aiops/` remain for the lab until the chart is verified there.

## Prerequisites

- Kubernetes 1.29 or newer, `helm` 3.18 or newer, `kubectl`.
- Envoy Gateway 1.9 with a `Gateway` that terminates TLS for `*.<parent domain>`
  and allows routes from every namespace (`allowedRoutes.namespaces.from: All`),
  or `gateway.create=true` and a `GatewayClass` to create one.
  The local stack's `infra/local/gateway/` shows both objects.
- cert-manager when the chart should issue the certificate (`gateway.tls.certificate.create`):
  1.21 on kind; any release that serves `cert-manager.io/v1` is enough, so reuse the one a cluster has (the lab node's is 1.11);
  otherwise a TLS Secret for `*.<parent domain>` in the Gateway's namespace.
- A parent domain with a wildcard DNS record pointing at the Gateway:
  the chart creates `ui.`, `api.`, `auth.`, `sso.` and, with Langflow, `langflow.<parent domain>`,
  and the backend creates `nb-`, `vdb-` and `inf-` hosts under it for every instance.
- The Kubeflow notebook controller for notebooks (`make kind-up` installs it locally).
- For GPU engines (vLLM, TGI, TEI, OPEA, fine-tune jobs):
  nodes that advertise `nvidia.com/gpu` with NVIDIA as the default container runtime and no GPU taint
  (the engine values set no `runtimeClassName` and no tolerations),
  the Prometheus operator CRDs (every engine chart defaults to `serviceMonitor.enabled: true`),
  and the model cache claim `hf-cache` in the release namespace (`backend.hfCache.create=true`).
  A first start downloads the model, which can take long on a slow link, and a killed download starts again from zero.
  `charts/vllm` 0.4.1 has a startup probe of two hours for that; on an older published chart the backend stretches the liveness delay instead
  (`VLLM_LIVENESS_INITIAL_DELAY_SECONDS` through `backend.env`, two hours by default; lower it, for example to `60`, once the chart in use renders the startup probe).
- Images: `ghcr.io/infracloudio/aiops-backend` and `aiops-frontend` (`global.imageTag`, default `main`).
  The `*-image.yml` workflows publish both on every push to `main` that changes `backend/` or `frontend/`,
  tagged `main` and the first seven characters of the commit SHA;
  `make chart-images` builds the same tag locally for kind.

## Values you must set

| Value | Meaning |
| --- | --- |
| `global.parentDomain` | the DNS suffix; the default `aiops.example.com` renders but resolves nowhere |
| `global.imageTag` | the image tag of both platform images |
| `gateway.name`, `gateway.namespace` | the existing Gateway (with `gateway.create=false`) |
| `gateway.tls.secretName` | with `gateway.create=true` or `gateway.tls.certificate.create=true` |
| `gateway.tls.certificate.issuerRef.name` | with `gateway.tls.certificate.create=true` |
| `global.caSecret` | a Secret with `ca.crt` when the Gateway's certificate comes from a private CA |
| `backend.hfCache.mount` | mount the `hf-cache` claim read-only into the API pod, so a starting model instance says how far its download is; with a `ReadWriteOnce` claim the API pod and the engine pods must share a node |
| `backend.hfCache.create`, `.size`, `.storageClass`, `.accessModes` | the `hf-cache` claim GPU engines mount; off by default, `ReadWriteMany` when GPU pods run on more than one node |
| `ui.grafanaUrl`, `ui.langflowUrl`, `ui.jaegerUrl` | tool URLs the UI embeds; served to the browser by `GET /v1alpha1/config/ui` |

Everything else has a working default; `charts/aiops-platform/values.yaml` documents every key.

## Secrets

One Secret, `aiops-platform-secrets` (`secrets.name`, fixed because the subcharts reference it by name), carries every credential:

| Key | Used by |
| --- | --- |
| `AUTH_SECRET` | the UI's session cookie (Auth.js) |
| `KEYCLOAK_CLIENT_SECRET` | the `aiops-gateway` client: the gateway policy (copied into `aiops-gateway-oidc`, key `client-secret`) and the realm import |
| `AUTOMATION_CLIENT_SECRET` | the `aiops-automation` client-credentials client (`hack/e2e-smoke.sh`, the smoke test) |
| `KEYCLOAK_ADMIN_PASSWORD` | the bundled Keycloak's `admin` user |
| `LITELLM_MASTER_KEY` | the backend's LiteLLM calls and the bundled proxy |
| `LITELLM_SALT_KEY` | encrypts provider keys stored by LiteLLM (copied into `aiops-litellm-env`); never change it |
| `DATABASE_USER`, `DATABASE_PASSWORD` | the bundled Postgres (`postgres` superuser) and the backend, Keycloak and LiteLLM connections |
| `HF_TOKEN` | the backend's `HF_API_TOKEN` (Hugging Face engines); empty by default |
| `NGC_API_KEY` | NVIDIA NIM; empty by default |
| `LANGFLOW_SUPERUSER_PASSWORD` | the bundled Langflow's break-glass superuser `aiops-admin` (`langflow.enabled`); required in `secrets.existingSecret` when Langflow is enabled, since the hook backfills a generated Secret only |

On the first install a pre-install hook generates the Secret with random values (`secrets.generate=true`);
on every later install or upgrade it keeps it.
To provide your own, create a Secret with the keys above and set `secrets.existingSecret=<name>`:
the hook copies it into `aiops-platform-secrets` on every install and upgrade,
so edit the source Secret and run `helm upgrade` to propagate a change.

Add the tokens after the install:

```bash
kubectl -n aiops-platform patch secret aiops-platform-secrets -p '{"stringData":{"HF_TOKEN":"hf_...","NGC_API_KEY":"nvapi-..."}}'
kubectl -n aiops-platform rollout restart deployment/aiops-platform-backend
```

`helm uninstall` leaves the three Secrets in place so a reinstall keeps its credentials and the LiteLLM salt;
delete the namespace to remove them.

## Install

```bash
helm dependency build charts/aiops-platform          # Bitnami postgresql 16.7.27, keycloak 25.2.0, litellm-helm 1.99.0 (pinned in Chart.yaml)
kubectl create namespace aiops-platform
helm upgrade --install aiops-platform charts/aiops-platform -n aiops-platform \
  --set global.parentDomain=platform.example.com \
  --set global.imageTag=main \
  --set gateway.name=aiops --set gateway.namespace=envoy-gateway-system \
  --timeout 15m
kubectl -n aiops-platform get pods
helm -n aiops-platform get notes aiops-platform
```

The backend runs the Alembic migrations when it starts (`db/migrate.py upgrade_to_head`),
so the first pod start creates the schema and the `default` organization;
`kubectl -n aiops-platform logs deployment/aiops-platform-backend | grep -i alembic` shows them.
Keycloak imports the realm `aiops` from the chart on its first start and skips the import afterwards;
the realm's clients are `aiops-ui` (public, PKCE, redirect `https://ui.<parent domain>/*`),
`aiops-gateway` (confidential, redirects `https://sso.<parent domain>/oauth2/callback` and `https://langflow.<parent domain>/oauth2/callback`)
and `aiops-automation` (client credentials).
`keycloak.devUsers=true` adds `admin`, `alice` and `bob` (password equals the user name) for a demo; leave it off elsewhere.
Without dev users, create people in the Admin Console (`https://auth.<parent domain>/admin/master/console/`, user `admin`, password from the Secret)
and put platform admins in the group `platform-admins`.

## Upgrade

With Helm 4, add `--server-side=false` to every `helm upgrade` of this chart.
The backend appends each notebook and vector database route to `targetRefs` of the shared policy `aiops-workloads-oidc`,
and the chart relies on Helm's client-side three-way merge to keep them.
Helm 4 applies server-side by default, owns the whole list, and fails the upgrade with a conflict on `.spec.targetRefs` once an instance exists.
That failure is safe. `--force-conflicts` is not: it resets the list to the chart's one entry,
and a route that is no longer in the policy is open to anyone who can reach the gateway.
`make chart-install` adds the flag on Helm 4.

Migrations run at backend startup, so an upgrade is:

```bash
kubectl -n aiops-platform exec statefulset/aiops-postgresql -- env PGPASSWORD="$(kubectl -n aiops-platform get secret aiops-platform-secrets -o jsonpath='{.data.DATABASE_PASSWORD}' | base64 -d)" \
  pg_dump -U postgres -Fc aiops > aiops-$(date +%Y%m%d).dump     # backup first, see below
helm dependency build charts/aiops-platform
helm upgrade aiops-platform charts/aiops-platform -n aiops-platform --reset-then-reuse-values --set global.imageTag=<new tag> --timeout 15m  # keeps a newer chart version's new defaults
kubectl -n aiops-platform rollout status deployment/aiops-platform-backend
kubectl -n aiops-platform logs deployment/aiops-platform-backend | grep -i alembic
```

A migration failure leaves the backend pod crash-looping and the old revision's rows untouched;
`helm rollback aiops-platform <previous revision>` restores the previous images,
and a migration that already ran must be reverted by restoring the backup (Alembic does not downgrade on startup).
The pre-install hook runs on every upgrade and keeps the existing Secret.

## Switch a dependency to an external system

Every dependency has an `enabled` switch and an `external` block; the backend, the UI and the gateway policy follow the switch.
`charts/aiops-platform/test/values-external.yaml` shows all three switched off; `make chart-lint` renders it.

### Postgres

1. Dump the three databases (`aiops`, `keycloak`, `litellm`) with `pg_dump` as under "Backup" and restore them on the external server.
2. Create a Secret with `DATABASE_PASSWORD` for the external user, or keep the platform Secret's value.
3. Set `postgresql.enabled=false`, `postgresql.external.{host,port,database,username,existingSecret}`,
   and because subchart values cannot follow the parent's,
   also `keycloak.externalDatabase.{host,port,user,database,existingSecret,existingSecretPasswordKey}` and `litellm.db.{endpoint,database,secret.name}`
   when those stay bundled.
4. `helm upgrade`; the backend reads `DATABASE_URL=postgresql://<host>:<port>` from the ConfigMap
   and `DATABASE_USER` and `DATABASE_PASSWORD` from the Secret.

### Keycloak

1. Import the realm into the external Keycloak: `charts/aiops-platform/files/realm-aiops.json` with `__PARENT_DOMAIN__` replaced and the two `${...}` secrets filled in,
   or create the three clients by hand with the redirect URIs above and the `aiops` client scope (audience `aiops-api`, realm roles, groups).
2. Create a Secret with `KEYCLOAK_CLIENT_SECRET` (the `aiops-gateway` client's secret), or keep the platform Secret's value.
3. Set `keycloak.enabled=false`, `keycloak.external.issuer=https://<host>/realms/aiops`, `keycloak.external.existingSecret`.
4. `helm upgrade`; the backend validates tokens against `<issuer>/protocol/openid-connect/certs`, the UI signs in against the issuer,
   and the gateway policy resolves the issuer over the network (no in-cluster backend reference).

### LiteLLM

1. Register the master key of the external proxy in a Secret under `LITELLM_MASTER_KEY`, or keep the platform Secret's value.
2. Set `litellm.enabled=false`, `litellm.external.url=https://<host>`, `litellm.external.existingSecret`.
3. `helm upgrade`; instances deployed before the switch must be re-registered (delete and launch again).
   An empty `litellm.external.url` runs the backend without LiteLLM: chat falls back to the instance's gateway host, embeddings and rerank answer 503.

## Langflow

`langflow.enabled=true` deploys Langflow (`langflow.image`, a `ReadWriteOnce` volume of `langflow.persistence.size`)
behind the gateway at `https://langflow.<parent domain>` on platform identity (ADR 0002):
its own `SecurityPolicy` logs the browser in, asks the backend who may open it, forwards the access token,
and Langflow verifies that token and keeps one Langflow user per platform user.
The backend then provisions each member's Langflow account with the organization's LiteLLM
(`LANGFLOW_API_URL` in the ConfigMap), so Langflow's model pickers list the organization's models.
With `langflow.enabled: false` and `ui.langflowUrl` naming a Langflow of your own on platform identity,
the backend provisions that one through its public address instead.
Three values matter:

- `langflow.ssrfAllowedHosts`: Langflow refuses private addresses otherwise.
  Flows reach models through LiteLLM only, so the default (empty) allows just the bundled LiteLLM Service;
  name an external LiteLLM's host here when it is a private address.
- `langflow.hostAliases`: Langflow fetches the realm's JWKS from the public issuer host over https
  (it refuses a plain-http URL), so on a cluster where that host does not resolve from a pod, alias it to the gateway,
  as `make chart-install` does for `frontend.hostAliases`; `global.caSecret` makes the pod trust a private CA.
- `LANGFLOW_SUPERUSER_PASSWORD` in the Secret: the break-glass superuser `aiops-admin`, never a person's login.

Keycloak imports the realm once, so an existing install adds `https://langflow.<parent domain>/oauth2/callback`
to the `aiops-gateway` client's redirect URIs in the Admin Console.
A rejected `SecurityPolicy` is not applied at all and leaves its route open,
so a post-install and post-upgrade hook Job (`<release>-policy-check`) waits until the controller reports `Accepted`
on the workloads policy and on Langflow's, and fails the release otherwise;
`kubectl -n <namespace> get securitypolicy -o jsonpath='{.items[*].status.ancestors[0].conditions}'` shows the reason.

## Backup and restore

```bash
NS=aiops-platform
PW=$(kubectl -n $NS get secret aiops-platform-secrets -o jsonpath='{.data.DATABASE_PASSWORD}' | base64 -d)
for db in aiops keycloak litellm; do
  kubectl -n $NS exec statefulset/aiops-postgresql -- env PGPASSWORD="$PW" pg_dump -U postgres -Fc "$db" > "$db-$(date +%Y%m%d).dump"
done
kubectl -n $NS get secret aiops-platform-secrets -o yaml > aiops-platform-secrets-$(date +%Y%m%d).yaml   # keep it with the dumps, out of git
```

Restore into a fresh install with the same Secret (apply the saved Secret before `helm install`, or pass it as `secrets.existingSecret`), then:

```bash
for db in aiops keycloak litellm; do
  kubectl -n $NS exec -i statefulset/aiops-postgresql -- env PGPASSWORD="$PW" pg_restore -U postgres -d "$db" --clean --if-exists < "$db-<date>.dump"
done
kubectl -n $NS rollout restart deployment/aiops-platform-backend statefulset/aiops-keycloak deployment/aiops-litellm
```

Instance releases (`ollama-<id8>` and the like) and the workload credential Secrets live in the instance namespace and are not part of the dump;
recreate instances after a restore into a new cluster.

## The chart on kind

```bash
make kind-up gateway-up ca-export trust-ca   # the dev stack's cluster, Gateway and CA
make chart-images                            # build and load the images of this checkout
make chart-smoke                             # chart-install plus the checks in hack/chart-smoke.sh
make chart-uninstall
```

The install lives in namespace `aiops-platform` under `platform.127.0.0.1.nip.io`, reuses the dev `Gateway` `aiops`,
adds a certificate for `*.platform.127.0.0.1.nip.io` (issued by the dev CA) to its https listener,
aliases `auth.platform.127.0.0.1.nip.io` to the Envoy Service inside the UI pod (nip.io resolves to the pod's own loopback address otherwise),
and imports the dev users.
Delete any running Ollama instance first: the node has room for the dev stack plus either an Ollama instance or this install, not both.
A later `make gateway-up` re-applies `infra/local/gateway/gateway.yaml`, whose https listener lists one certificate,
and so drops the platform certificate from the listener again;
the patch in `make chart-install` is idempotent, so re-running it restores the entry.

## Uninstall

```bash
helm -n aiops-platform uninstall aiops-platform
```

Helm removes what it installed and leaves behind, on purpose or by Helm's hook rules:
the three Secrets the hook wrote (`aiops-platform-secrets`, `aiops-gateway-oidc`, `aiops-litellm-env`),
the hook's own objects (ServiceAccount, Role, RoleBinding and ConfigMap `aiops-platform-secrets-init`; the Job is deleted after it succeeds),
the Postgres PersistentVolumeClaim (`data-aiops-postgresql-0`),
and the TLS Secret cert-manager wrote for the Certificate.
Delete them by hand, or delete the namespace when nothing else lives in it;
on kind `make chart-uninstall` deletes the namespace and the certificate Secret.

## A bare-metal cluster

The chart renders no `GatewayClass` and no `EnvoyProxy`, and a cluster without the kind stack needs both:
the `EnvoyProxy` must order the `oauth2` filter before `ext_authz` (login fails without it)
and expose the Envoy Service as a `LoadBalancer`.
`infra/lab/` holds these objects, a CA issuer, monitoring and GPU operator values and the install order for the lab's k3s GPU node,
with `charts/aiops-platform/test/values-lab.yaml` as the chart fixture.
Check what the cluster runs already before installing cluster-level components:
`make gateway-up` installs cert-manager and must not run against a cluster that has one.
`hack/lab-dry-run.sh` automates that check for the lab node.

## Known limitations

- The backend attaches every `nb-`/`vdb-` browser route to the `aiops-workloads-oidc` SecurityPolicy the chart renders in the release namespace,
  and fails the instance install (route deleted again, row `Failed` with the reason) when it cannot;
  API-key routes (`vdb-*-api`, `inf-`) get their own policy.
  With `gateway.enabled=false` the ConfigMap carries no `AIOPS_PARENT_DOMAIN`, so the backend creates no routes or policies at all;
  setting `AIOPS_PARENT_DOMAIN` through `backend.env` with the gateway off creates the routes but no policy exists to attach them to,
  so every notebook and vector database launch fails with that reason (inference launches keep working behind their API-key policy).
- On kind, a vector database or notebook launch from the chart-installed backend calls `ensure_reference_grant("aiops-platform")`
  (`ensure_reference_grant` and `REFERENCE_GRANTS` in `backend/utils/gateway.py`,
  from `_ensure_gateway_policies` in `vectordb_controller.py` and `notebooks_controller.py`),
  which appends the namespace to the dev stack's ReferenceGrants `auth/allow-ai-stack-securitypolicy-to-keycloak` and `ai-stack/allow-securitypolicy-to-aiops-backend`.
  `make chart-uninstall` does not revert that entry; `make auth-up` and `make gateway-up` re-apply the grants and drop it.
- Keycloak keeps its sessions in the bundled Postgres, so a Keycloak restart does not sign everyone out (unlike the dev stack's in-memory `start-dev`).
- `:main` moves with every application commit; pin `global.imageTag` to a SHA tag for a reproducible install.
  Both images carry the same tag, and a commit that changes only charts or docs publishes none,
  so the newest tag is what `make image-tag` prints on an up-to-date `main`
  (the last commit that touched `backend/`, `frontend/` or the two image workflows), not `HEAD`.
- The chart is verified on kind and, since 2026-09-18, on the lab's k3s GPU node (chart 0.3.0, image tag `1f87e31`):
  `infra/lab/README.md` has the install order and what that first run showed, and `hack/chart-smoke.sh --skip-install` passed there.
  GPU engines launched from the UI are not verified there yet.
  The legacy `infra/aiops/` manifests describe the retired kubespray lab and can now be retired (`infra/aiops/README.md`).
- The post-install policy check waits `gateway.policyCheck.timeoutSeconds` (10 minutes) for the gateway controller to accept the policies,
  which it does only once the backend and Keycloak pods are ready. If a first install on a slow registry still fails there,
  run the same `helm upgrade --install` again when the pods are ready.
