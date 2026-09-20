#!/usr/bin/env bash
# Smoke test for charts/aiops-platform on the local kind stack (make chart-smoke).
#
#   - make chart-install (skip with --skip-install)
#   - the backend and frontend Deployments are Available
#   - GET https://api.<pd>/health answers {"message":"OK"} through the gateway
#   - GET https://api.<pd>/v1alpha1/config/ui reports authMode oidc
#   - GET https://api.<pd>/v1alpha1/models without a token is 401
#   - the realm's discovery document names the public issuer
#   - GET https://ui.<pd>/login is 200 and offers "Sign in with Keycloak"
#   - the UI pod reaches the public issuer host (hostAliases and the CA)
#   - a client-credentials token from aiops-automation lists the models
#
# Requires: curl, jq, kubectl, helm, make; infra/local/ca/ca.crt (make ca-export).
set -euo pipefail

CHART_RELEASE="${CHART_RELEASE:-aiops-platform}"
CHART_NAMESPACE="${CHART_NAMESPACE:-aiops-platform}"
PARENT_DOMAIN="${PARENT_DOMAIN:-platform.127.0.0.1.nip.io}"
CA_CERT="${CA_CERT:-infra/local/ca/ca.crt}"
SKIP_INSTALL=false

for arg in "$@"; do
  case "$arg" in
    --skip-install) SKIP_INSTALL=true ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

for bin in curl jq kubectl helm make; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "FAIL: required tool '$bin' not found on PATH" >&2
    exit 1
  fi
done
[[ -s "$CA_CERT" ]] || { echo "FAIL: $CA_CERT is missing (make ca-export)" >&2; exit 1; }

API="https://api.$PARENT_DOMAIN"
UI="https://ui.$PARENT_DOMAIN"
AUTH="https://auth.$PARENT_DOMAIN"
FAILURES=0
BODY=$(mktemp)
trap 'rm -f "$BODY"' EXIT

pass() { printf "PASS  %-58s %s\n" "$1" "${2:-}"; }
fail() { printf "FAIL  %-58s %s\n" "$1" "${2:-}"; FAILURES=$((FAILURES + 1)); }

# get <url> [curl args...]: prints the status, body in $BODY.
get() {
  local url=$1; shift
  curl --cacert "$CA_CERT" -s -o "$BODY" -w '%{http_code}' "$@" "$url" || echo 000
}

if ! $SKIP_INSTALL; then
  make chart-install CHART_RELEASE="$CHART_RELEASE" CHART_NAMESPACE="$CHART_NAMESPACE" CHART_PARENT_DOMAIN="$PARENT_DOMAIN"
fi

for deploy in "$CHART_RELEASE-backend" "$CHART_RELEASE-frontend"; do
  if kubectl -n "$CHART_NAMESPACE" wait --for=condition=Available "deployment/$deploy" --timeout=600s >/dev/null 2>&1; then
    pass "deployment $deploy is Available"
  else
    fail "deployment $deploy is Available"
  fi
done

status=$(get "$API/health")
if [[ "$status" == 200 && "$(jq -r .message "$BODY" 2>/dev/null)" == "OK" ]]; then
  pass "GET $API/health" "$status"
else
  fail "GET $API/health" "$status $(head -c 200 "$BODY")"
fi

status=$(get "$API/v1alpha1/config/ui")
if [[ "$status" == 200 && "$(jq -r .authMode "$BODY" 2>/dev/null)" == "oidc" ]]; then
  pass "GET /v1alpha1/config/ui reports authMode oidc"
else
  fail "GET /v1alpha1/config/ui reports authMode oidc" "$status $(head -c 200 "$BODY")"
fi

status=$(get "$API/v1alpha1/models")
if [[ "$status" == 401 ]]; then
  pass "GET /v1alpha1/models without a token is 401"
else
  fail "GET /v1alpha1/models without a token is 401" "$status"
fi

status=$(get "$AUTH/realms/aiops/.well-known/openid-configuration")
if [[ "$status" == 200 && "$(jq -r .issuer "$BODY" 2>/dev/null)" == "$AUTH/realms/aiops" ]]; then
  pass "realm discovery names $AUTH/realms/aiops"
else
  fail "realm discovery names $AUTH/realms/aiops" "$status $(jq -r .issuer "$BODY" 2>/dev/null)"
fi

status=$(get "$UI/login")
if [[ "$status" == 200 ]] && grep -q "Sign in with Keycloak" "$BODY"; then
  pass "GET $UI/login offers the Keycloak sign-in"
else
  fail "GET $UI/login offers the Keycloak sign-in" "$status"
fi

if kubectl -n "$CHART_NAMESPACE" exec "deploy/$CHART_RELEASE-frontend" -- \
  node -e "fetch('$AUTH/realms/aiops').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))" >/dev/null 2>&1; then
  pass "the UI pod reaches $AUTH (hostAliases, CA)"
else
  fail "the UI pod reaches $AUTH (hostAliases, CA)"
fi

automation_secret=$(kubectl -n "$CHART_NAMESPACE" get secret aiops-platform-secrets \
  -o jsonpath='{.data.AUTOMATION_CLIENT_SECRET}' | base64 -d)
token=$(curl --cacert "$CA_CERT" -s -d grant_type=client_credentials -d client_id=aiops-automation \
  -d client_secret="$automation_secret" "$AUTH/realms/aiops/protocol/openid-connect/token" | jq -r '.access_token // empty')
if [[ -z "$token" ]]; then
  fail "client-credentials token from aiops-automation"
else
  pass "client-credentials token from aiops-automation"
  status=$(get "$API/v1alpha1/models" -H "Authorization: Bearer $token")
  if [[ "$status" == 200 && "$(jq 'length' "$BODY" 2>/dev/null)" -gt 0 ]]; then
    pass "GET /v1alpha1/models with the token lists the catalog"
  else
    fail "GET /v1alpha1/models with the token lists the catalog" "$status"
  fi
fi

# A deployed MCP server brings a NetworkPolicy, and Helm installs it with
# the backend's own account. A laptop backend runs as a cluster admin, so
# only here does a missing RBAC rule show.
backend_sa=$(kubectl -n "$CHART_NAMESPACE" get deployment "$CHART_RELEASE-backend" \
  -o jsonpath='{.spec.template.spec.serviceAccountName}' 2>/dev/null)
if [[ "$(kubectl auth can-i create networkpolicies.networking.k8s.io -n "$CHART_NAMESPACE" \
  --as="system:serviceaccount:$CHART_NAMESPACE:$backend_sa" 2>/dev/null)" == yes ]]; then
  pass "the backend's account may create a NetworkPolicy (MCP deploy)"
else
  fail "the backend's account may create a NetworkPolicy (MCP deploy)" "$backend_sa"
fi
if kubectl -n "$CHART_NAMESPACE" get configmap "$CHART_RELEASE-backend-config" \
  -o jsonpath='{.data.AIOPS_LITELLM_POD_LABELS}' 2>/dev/null | grep -q 'app.kubernetes.io/name=litellm'; then
  pass "the backend knows which pods are the proxy's"
else
  fail "the backend knows which pods are the proxy's"
fi

if (( FAILURES > 0 )); then
  echo "$FAILURES check(s) failed" >&2
  exit 1
fi
echo "All chart smoke checks passed."
