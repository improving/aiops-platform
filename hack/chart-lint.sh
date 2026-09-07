#!/usr/bin/env bash
# Lint and render checks for charts/aiops-platform (make chart-lint):
#   helm lint --strict with the default values and the external fixture,
#   helm template with the default, external and kind values, and
#   assertions on what each render must and must not contain.
# Requires: helm (and network for helm dependency build).
set -euo pipefail
cd "$(dirname "$0")/.."

CHART=charts/aiops-platform
FAILURES=0

pass() { printf "PASS  %s\n" "$1"; }
fail() { printf "FAIL  %s\n" "$1" >&2; FAILURES=$((FAILURES + 1)); }
# expect <name> <extended regex> <text>: the text matches.
expect() { if printf '%s' "$3" | grep -qE -- "$2"; then pass "$1"; else fail "$1"; fi; }
# reject <name> <extended regex> <text>: the text does not match.
reject() { if printf '%s' "$3" | grep -qE -- "$2"; then fail "$1"; else pass "$1"; fi; }

helm dependency build "$CHART" >/dev/null
helm lint --strict "$CHART"
helm lint --strict "$CHART" -f "$CHART/test/values-external.yaml"

default=$(helm template aiops-platform "$CHART" -n aiops-platform)
external=$(helm template aiops-platform "$CHART" -n aiops-platform -f "$CHART/test/values-external.yaml")
kind_render=$(helm template aiops-platform "$CHART" -n aiops-platform -f "$CHART/test/values-kind.yaml")

# --- default values: everything bundled -------------------------------------
expect "default renders the backend Deployment" 'name: aiops-platform-backend$' "$default"
expect "default renders the frontend Deployment" 'name: aiops-platform-frontend$' "$default"
expect "default renders Postgres" 'name: aiops-postgresql$' "$default"
expect "default renders Keycloak" 'name: aiops-keycloak$' "$default"
expect "default renders LiteLLM" 'name: aiops-litellm$' "$default"
expect "default routes the ui host" '"ui\.aiops\.example\.com"' "$default"
expect "default routes the api host" '"api\.aiops\.example\.com"' "$default"
expect "default routes the auth host" '"auth\.aiops\.example\.com"' "$default"
expect "default routes the sso host" '"sso\.aiops\.example\.com"' "$default"
expect "default issuer is the bundled realm" 'OIDC_ISSUER: "https://auth\.aiops\.example\.com/realms/aiops"' "$default"
expect "default JWKS is fetched in-cluster" 'OIDC_JWKS_URL: "http://aiops-keycloak/realms/aiops/protocol/openid-connect/certs"' "$default"
expect "default DATABASE_URL is the bundled server" 'DATABASE_URL: "postgresql://aiops-postgresql:5432"' "$default"
expect "default LITELLM_URL is the bundled proxy" 'LITELLM_URL: "http://aiops-litellm:4000"' "$default"
expect "default Postgres creates the keycloak and litellm databases" 'CREATE DATABASE keycloak' "$default"
expect "default realm keeps the automation service account" '"username": "service-account-aiops-automation"' "$default"
reject "default realm has no dev users" '"username": "alice"' "$default"
expect "default realm reads the gateway secret from the environment" '\$\{KEYCLOAK_CLIENT_SECRET\}' "$default"
expect "default KC_HOSTNAME is the auth host" 'KC_HOSTNAME: "https://auth\.aiops\.example\.com"' "$default"
expect "default ui route has a stream timeout" 'streamIdleTimeout: 10m' "$default"
reject "default renders no Gateway" '^kind: Gateway$' "$default"
# The backend attaches nb-/vdb- routes to the OIDC policy of its own
# namespace: the policy must render without a namespace of its own (so it
# lands in the release namespace with everything else), with the sso
# callback route first, and the backend must run in that same namespace.
oidc_policy=$(printf '%s' "$default" | awk 'BEGIN { RS = "---\n" } /kind: SecurityPolicy\n/ && /name: aiops-workloads-oidc\n/')
expect "default renders the shared OIDC policy" '^kind: SecurityPolicy$' "$oidc_policy"
reject "default OIDC policy carries no namespace of its own" '^  namespace:' "$(printf '%s' "$oidc_policy" | sed -n '/^metadata:/,/^spec:/p')"
expect "default OIDC policy targets the sso route first" 'name: sso$' "$(printf '%s' "$oidc_policy" | grep -A3 -- 'targetRefs:')"
expect "default backend runs in the release namespace" 'AIOPS_NAMESPACE: "aiops-platform"' "$default"

# --- external fixture: every dependency off ----------------------------------
reject "external renders no Postgres" 'name: aiops-postgresql' "$external"
reject "external renders no Keycloak" 'name: aiops-keycloak' "$external"
reject "external renders no LiteLLM" 'name: aiops-litellm$' "$external"
reject "external renders no auth route" '"auth\.platform\.example\.com"' "$external"
expect "external DATABASE_URL" 'DATABASE_URL: "postgresql://db\.internal\.example\.com:5432"' "$external"
expect "external DATABASE_USER" 'DATABASE_USER: "aiops"' "$external"
expect "external database password comes from aiops-db" 'name: aiops-db$' "$external"
expect "external OIDC_ISSUER" 'OIDC_ISSUER: "https://sso\.example\.com/realms/aiops"' "$external"
reject "external has no OIDC_JWKS_URL" 'OIDC_JWKS_URL' "$external"
expect "external LITELLM_URL" 'LITELLM_URL: "https://litellm\.example\.com"' "$external"
expect "external master key comes from aiops-litellm-key" 'name: aiops-litellm-key$' "$external"
expect "external policy issuer" 'issuer: "https://sso\.example\.com/realms/aiops"' "$external"
reject "external policy has no Keycloak backendRef" 'backendRefs:[[:space:]]*$' "$(printf '%s' "$external" | sed -n '/kind: SecurityPolicy/,/extAuth:/p')"
expect "external renders a Gateway" '^kind: Gateway$' "$external"
expect "external renders the Certificate" 'name: aiops-platform-wildcard$' "$external"
expect "external Certificate covers the wildcard" '"\*\.platform\.example\.com"' "$external"
expect "external GRAFANA_URL" 'GRAFANA_URL: "https://grafana\.example\.com"' "$external"

# --- kind fixture --------------------------------------------------------------
expect "kind Certificate is issued by aiops-ca" 'name: aiops-ca$' "$kind_render"
expect "kind Certificate lives in the gateway namespace" 'namespace: envoy-gateway-system' "$kind_render"
expect "kind realm carries the dev users" '"username": "alice"' "$kind_render"
expect "kind routes attach to the dev Gateway" 'name: aiops$' "$kind_render"

# --- the secrets hook -----------------------------------------------------------
expect "default hook generates the platform Secret" 'value: "true"' "$(printf '%s' "$default" | grep -A1 -- 'name: GENERATE')"
expect "default hook reads the gateway secret from the platform Secret" 'value: "aiops-platform-secrets"' "$(printf '%s' "$default" | grep -A1 -- 'name: KEYCLOAK_SECRET')"
expect "external hook copies the source Secret" 'value: "my-platform-secrets"' "$(printf '%s' "$external" | grep -A1 -- 'name: SOURCE_SECRET')"
expect "external hook does not generate" 'value: "false"' "$(printf '%s' "$external" | grep -A1 -- 'name: GENERATE')"
expect "external hook reads the gateway secret from aiops-oidc" 'value: "aiops-oidc"' "$(printf '%s' "$external" | grep -A1 -- 'name: KEYCLOAK_SECRET')"
expect "external hook skips the LiteLLM env Secret" 'value: "false"' "$(printf '%s' "$external" | grep -A1 -- 'name: WRITE_LITELLM_ENV')"
expect "hook script is embedded" 'apply_secret aiops-gateway-oidc' "$default"
expect "hook script patches missing keys into an existing Secret" 'kubectl.*patch secret' "$default"

# --- never a credential in a render -------------------------------------------
reject "no dev literal in any render" 'dev-gateway-secret|dev-automation-secret|sk-dev-litellm-master|dev-auth-secret-change-me|changeme' "$default$external$kind_render"

if (( FAILURES > 0 )); then
  echo "$FAILURES check(s) failed" >&2
  exit 1
fi
echo "All chart checks passed."
