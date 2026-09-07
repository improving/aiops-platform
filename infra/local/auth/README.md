# Local Keycloak and the dev realm

Manifests applied by `make auth-up` (see the repository `Makefile`).
Together they run Keycloak 26.7.3 in namespace `auth`,
reachable through the gateway at `https://auth.127.0.0.1.nip.io/`,
with the dev realm `aiops` imported on every start.
See `docs/local-dev.md` section "Keycloak" for the full walkthrough,
the dev users and clients, and how to edit the realm.

## Files

- `keycloak.yaml` -- Namespace `auth`;
  Service `keycloak` (port 8080 for traffic, 9000 for health);
  Deployment `keycloak` (`quay.io/keycloak/keycloak:26.7.3`,
  `start-dev --import-realm`, realm mounted read-only from the
  `keycloak-realm` ConfigMap that `make auth-up` builds from
  `realm-aiops.json`);
  `HTTPRoute` `keycloak` (hostname `auth.127.0.0.1.nip.io`,
  attached to `Gateway` `aiops` in `envoy-gateway-system`);
  a `ReferenceGrant` letting a `SecurityPolicy` in `ai-stack` reference
  the `keycloak` Service from a different namespace, which Gateway API
  requires explicitly
  (`backend/utils/gateway.py` `ensure_reference_grant` adds other
  namespaces to it).
- `gateway-client-secret.yaml` -- Secret `aiops-gateway-oidc` in `ai-stack`,
  the dev value for the confidential `aiops-gateway` OIDC client's secret
  (key `client-secret`).
  `backend/utils/gateway.py` `ensure_gateway_client_secret` copies it into
  any other namespace an instance installs into.
- `workloads-oidc-policy.yaml` -- the shared OIDC + ext-authz
  `SecurityPolicy` `aiops-workloads-oidc` in `ai-stack` for every browser
  route (see "Redirect URIs and the shared OIDC policy" below);
  created by `make auth-up` only when missing.
- `realm-aiops.json` -- the realm export: clients `aiops-ui`, `aiops-gateway`,
  `aiops-automation`;
  a shared `aiops` client scope (audience `aiops-api` plus group
  membership) and the standard built-in scopes (`roles`, `profile`,
  `email`, `web-origins`, `basic`, `acr`) it depends on -- see "Why the
  realm defines the built-in scopes" below;
  realm roles `admin`/`member`/`viewer`;
  groups `platform-admins`/`platform-members`;
  dev users `admin`/`alice`/`bob`;
  disabled `google`/`github` identity providers with placeholder
  credentials.

## Why the realm defines the built-in scopes

Keycloak only auto-seeds its built-in default client scopes (`roles`,
`profile`, `email`, `web-origins`, `basic`, `acr`) when a realm is created
*without* a `clientScopes` array at all.
`--import-realm` does a *full* import, and as soon as `realm-aiops.json`
defines its own `clientScopes` entry (the custom `aiops` scope), that
auto-seeding does not happen -- any `defaultClientScopes` reference to a
scope that isn't also defined in the file is silently dropped (Keycloak
logs `Referenced client scope 'X' doesn't exist. Ignoring` and the token
never gets that claim). `realm-aiops.json` defines the six built-ins
explicitly, with their standard mappers, alongside `aiops`, so
`realm_access.roles`, `groups`, `email`, `preferred_username`, `name` and
CORS (`web-origins`) all actually reach the token. Add a new default scope
reference the same way if you extend the realm.
A full import also takes every protocol mapper's `config` literally:
the `basic` scope's `sub` mapper needs `access.token.claim: "true"` spelled
out (Keycloak's own default), or access tokens carry no `sub` claim and the
API rejects them with `The token has no subject`.

## Redirect URIs and the shared OIDC policy

Keycloak 26.7.3 does not glob-match a `*` placed before a literal path in
a redirect URI (confirmed live during the Task 0 spike),
and Envoy Gateway names its OIDC cookies with a suffix derived from the
`SecurityPolicy`, so only the policy that started a login can finish it
(Task 10 spike; both in
`docs/superpowers/plans/2026-09-04-authentication-gateway-notes.md`
under "Spike results").
Therefore `aiops-gateway` has exactly one redirect URI,
`https://sso.127.0.0.1.nip.io/oauth2/callback`,
and one `SecurityPolicy`, `aiops-workloads-oidc` in `ai-stack`
(`workloads-oidc-policy.yaml`), targets the `sso` callback route
(`infra/local/gateway/sso.yaml`) plus every instance browser route;
`backend/utils/gateway.py` adds and removes the instance routes in the
`targetRefs` of the policy of the route's own namespace
(the umbrella chart renders the same policy in its release namespace),
and fails the instance install when the route cannot be attached.
`make auth-up` creates the policy only when it is missing, so a re-import
does not reset the list.
See `docs/local-dev.md` section "Workload access".
