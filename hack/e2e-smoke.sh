#!/usr/bin/env bash
# End-to-end smoke test for the aiops-platform local dev stack.
#
# Exercises the backend control-plane API against a real kind cluster:
#   - health check
#   - catalog listings (vectordb, models, engines)
#   - create a Qdrant vector DB instance, wait for it to be Ready, fetch its
#     API key and curl /collections on the "-api" gateway host with and
#     without the key (or its health endpoint through a port-forward when
#     there is no gateway)
#   - create a Jupyter notebook instance, wait for it to be Running, curl its
#     base path through a port-forward (skip with --skip-notebook)
#   - launch qwen3:0.6b on the Ollama engine, wait for it to be Ready and ask
#     for one chat completion through /v1alpha1/chat/completions, then launch
#     all-minilm:33m and embed one sentence through /v1alpha1/embeddings
#     (skip both with --skip-ollama; the first run pulls the Ollama image and
#     the models; embeddings need LiteLLM, see 'make litellm-up')
#   - delete every instance it created
#
# Requires: curl, jq, kubectl. Run via `make e2e-smoke` or directly.
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
NAMESPACE="${NAMESPACE:-ai-stack}"
# Used to verify a stored https:// endpoint (gateway TLS) instead of
# port-forwarding, when the backend has AIOPS_PARENT_DOMAIN set. Also passed
# to curl for the token request below.
CA_CERT="${CA_CERT:-infra/local/ca/ca.crt}"
# When AUTH_MODE is not "disabled" every backend call needs a bearer token;
# obtained via client credentials from the automation client (see
# fetch_token below). AUTH_MODE=disabled matches the backend's own env var so
# `make e2e-smoke` and the backend it is pointed at agree on whether a token
# is required.
AUTH_MODE="${AUTH_MODE:-oidc}"
OIDC_ISSUER="${OIDC_ISSUER:-https://auth.127.0.0.1.nip.io/realms/aiops}"
AUTOMATION_CLIENT_ID="${AUTOMATION_CLIENT_ID:-aiops-automation}"
AUTOMATION_CLIENT_SECRET="${AUTOMATION_CLIENT_SECRET:-dev-automation-secret}"
SKIP_NOTEBOOK=false
SKIP_OLLAMA=false

for arg in "$@"; do
  case "$arg" in
    --skip-notebook) SKIP_NOTEBOOK=true ;;
    --skip-ollama) SKIP_OLLAMA=true ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

for bin in curl jq kubectl; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "FAIL: required tool '$bin' not found on PATH" >&2
    exit 1
  fi
done

# --- bookkeeping -----------------------------------------------------------

FAILURES=0
VECTORDB_INSTANCE_ID=""
NOTEBOOK_INSTANCE_ID=""
INFERENCE_INSTANCE_ID=""
PF_PID=""
TOKEN=""
API_BODY_FILE=/tmp/e2e-api-body.json
API_STATUS=""

pass() { printf "PASS  %-55s %s\n" "$1" "${2:-}"; }
fail() { printf "FAIL  %-55s %s\n" "$1" "${2:-}"; FAILURES=$((FAILURES + 1)); }
info() { printf "INFO  %s\n" "$1"; }

# --- authentication ----------------------------------------------------------
#
# The backend enforces AUTH_MODE=oidc by rejecting every request without a
# valid bearer token (401). Obtain one with the client-credentials grant from
# the automation client, and refresh it once if a call ever answers 401 (the
# access token is short-lived; a slow step can outlive it).

fetch_token() {
  [[ "$AUTH_MODE" == "disabled" ]] && return
  local status
  status=$(curl -sS -o /tmp/e2e-token.json -w "%{http_code}" --cacert "$CA_CERT" \
    -d grant_type=client_credentials \
    -d client_id="$AUTOMATION_CLIENT_ID" \
    -d client_secret="$AUTOMATION_CLIENT_SECRET" \
    "$OIDC_ISSUER/protocol/openid-connect/token") || status="000"
  if [[ "$status" != "200" ]]; then
    echo "FAIL: could not obtain an automation token from $OIDC_ISSUER (http_status=$status)" >&2
    cat /tmp/e2e-token.json 2>/dev/null >&2 || true
    exit 1
  fi
  TOKEN=$(jq -r '.access_token' /tmp/e2e-token.json)
}

# api_request METHOD PATH [JSON_BODY]
# Sends one call to $BACKEND_URL, with the bearer token attached when one was
# obtained. Sets API_STATUS and writes the response body to $API_BODY_FILE.
# Retries once, after fetching a fresh token, on a 401.
api_call() {
  local method="$1" path="$2" data="${3:-}"
  local args=(-sS -o "$API_BODY_FILE" -w "%{http_code}" -X "$method")
  [[ -n "$TOKEN" ]] && args+=(-H "Authorization: Bearer $TOKEN")
  [[ -n "$data" ]] && args+=(-H "Content-Type: application/json" -d "$data")
  API_STATUS=$(curl "${args[@]}" "$BACKEND_URL$path") || API_STATUS="000"
}

api_request() {
  local method="$1" path="$2" data="${3:-}"
  api_call "$method" "$path" "$data"
  if [[ "$API_STATUS" == "401" && -n "$TOKEN" ]]; then
    info "got 401 from $method $path; refreshing the automation token"
    fetch_token
    api_call "$method" "$path" "$data"
  fi
}

api_get() { api_request GET "$1"; }
api_post() { api_request POST "$1" "$2"; }
api_delete() { api_request DELETE "$1"; }

stop_port_forward() {
  if [[ -n "$PF_PID" ]] && kill -0 "$PF_PID" 2>/dev/null; then
    kill "$PF_PID" 2>/dev/null || true
    wait "$PF_PID" 2>/dev/null || true
  fi
  PF_PID=""
}

cleanup() {
  stop_port_forward
  if [[ -n "$VECTORDB_INSTANCE_ID" ]]; then
    info "cleanup: deleting vectordb instance $VECTORDB_INSTANCE_ID"
    api_delete "/v1alpha1/vectordb_instances/$VECTORDB_INSTANCE_ID" || true
  fi
  if [[ -n "$NOTEBOOK_INSTANCE_ID" ]]; then
    info "cleanup: deleting notebook instance $NOTEBOOK_INSTANCE_ID"
    api_delete "/v1alpha1/notebooks/$NOTEBOOK_INSTANCE_ID" || true
  fi
  if [[ -n "$INFERENCE_INSTANCE_ID" ]]; then
    info "cleanup: deleting inference instance $INFERENCE_INSTANCE_ID"
    api_delete "/v1alpha1/inferenceInstance/$INFERENCE_INSTANCE_ID" || true
  fi
}
trap cleanup EXIT

start_ts=$(date +%s)
elapsed() { echo "$(( $(date +%s) - start_ts ))s"; }

# --- 1. health ---------------------------------------------------------------

step_health() {
  api_get "/health"
  if [[ "$API_STATUS" == "200" ]] && [[ "$(jq -r '.message' "$API_BODY_FILE" 2>/dev/null)" == "OK" ]]; then
    pass "GET /health" "$(elapsed)"
  else
    fail "GET /health" "http_status=$API_STATUS body=$(cat "$API_BODY_FILE" 2>/dev/null)"
  fi
}

# --- 2. catalogs ---------------------------------------------------------------

step_catalog() {
  local path="$1" label="$2"
  local count
  api_get "$path"
  count=$(jq 'length' "$API_BODY_FILE" 2>/dev/null || echo 0)
  if [[ "$count" -gt 0 ]]; then
    pass "GET $path ($label)" "count=$count $(elapsed)"
  else
    fail "GET $path ($label)" "http_status=$API_STATUS count=$count"
  fi
}

# --- 3. qdrant vectordb instance ------------------------------------------------

step_create_vectordb() {
  local qdrant_id
  api_get "/v1alpha1/vectordb"
  qdrant_id=$(jq -r '.[] | select(.name == "Qdrant") | .id' "$API_BODY_FILE" | head -1)
  if [[ -z "$qdrant_id" || "$qdrant_id" == "null" ]]; then
    fail "resolve Qdrant catalog id" "not found in /v1alpha1/vectordb (http_status=$API_STATUS)"
    return
  fi
  info "Qdrant catalog id: $qdrant_id"

  api_post "/v1alpha1/vectordb_instances" \
    "{\"vectorDB\":{\"id\":\"$qdrant_id\"},\"configParams\":{\"serviceType\":\"ClusterIP\"}}"
  if [[ "$API_STATUS" != "201" ]]; then
    fail "POST /v1alpha1/vectordb_instances" "http_status=$API_STATUS body=$(cat "$API_BODY_FILE")"
    return
  fi
  VECTORDB_INSTANCE_ID=$(jq -r '.id' "$API_BODY_FILE")
  pass "POST /v1alpha1/vectordb_instances" "id=$VECTORDB_INSTANCE_ID $(elapsed)"
}

step_wait_vectordb_ready() {
  [[ -z "$VECTORDB_INSTANCE_ID" ]] && { fail "wait for vectordb instance Ready" "no instance id (create failed)"; return; }
  local deadline=$(( $(date +%s) + 600 ))
  local endpoint="" ready="false"
  while [[ $(date +%s) -lt $deadline ]]; do
    api_get "/v1alpha1/vectordb_instances/$VECTORDB_INSTANCE_ID"
    endpoint=$(jq -r '.endpoint // empty' "$API_BODY_FILE" 2>/dev/null || echo "")
    ready=$(jq -r '.ready // false' "$API_BODY_FILE" 2>/dev/null || echo "false")
    if [[ -n "$endpoint" && "$ready" == "true" ]]; then
      pass "vectordb instance Ready" "endpoint=$endpoint $(elapsed)"
      return
    fi
    sleep 5
  done
  fail "wait for vectordb instance Ready" "timed out after 10m (endpoint=$endpoint ready=$ready)"
}

step_qdrant_healthz() {
  [[ -z "$VECTORDB_INSTANCE_ID" ]] && { fail "curl Qdrant /healthz" "no instance id"; return; }

  # Behind the gateway, the SDK ("-api") host is deterministic and stored
  # as soon as AIOPS_PARENT_DOMAIN is set on the backend; curl it directly
  # instead of port-forwarding to the Service. The host is protected by
  # the instance API key (a SecurityPolicy on the route), so first read
  # the key through the API (the automation user owns the instance and
  # gets the one-time value), then check both the 401 and the 200.
  local api_endpoint
  api_get "/v1alpha1/vectordb_instances/$VECTORDB_INSTANCE_ID"
  api_endpoint=$(jq -r '.api_endpoint // empty' "$API_BODY_FILE" 2>/dev/null || echo "")
  if [[ "$api_endpoint" == https://* ]]; then
    local key url="${api_endpoint}collections"
    api_get "/v1alpha1/credentials/vdb/$VECTORDB_INSTANCE_ID"
    key=$(jq -r '.value // empty' "$API_BODY_FILE" 2>/dev/null || echo "")
    if [[ "$API_STATUS" != "200" || -z "$key" ]]; then
      fail "GET /v1alpha1/credentials/vdb/{id}" "http_status=$API_STATUS body=$(cat "$API_BODY_FILE")"
      return
    fi
    pass "GET /v1alpha1/credentials/vdb/{id}" "key=$(jq -r '.key' "$API_BODY_FILE") value=<redacted> $(elapsed)"

    # The policy is programmed into Envoy a moment after the route; give
    # both checks a few attempts.
    local code attempt
    for attempt in $(seq 1 6); do
      code=$(curl -sS --cacert "$CA_CERT" -o /dev/null -w "%{http_code}" "$url" || echo 000)
      [[ "$code" == "401" ]] && break
      sleep 5
    done
    if [[ "$code" == "401" ]]; then
      pass "curl Qdrant /collections via gateway without a key" "http_status=$code $(elapsed)"
    else
      fail "curl Qdrant /collections via gateway without a key" "expected 401, http_status=$code url=$url"
    fi
    for attempt in $(seq 1 6); do
      code=$(curl -sS --cacert "$CA_CERT" -o /dev/null -w "%{http_code}" -H "api-key: $key" "$url" || echo 000)
      [[ "$code" == "200" ]] && break
      sleep 5
    done
    if [[ "$code" == "200" ]]; then
      pass "curl Qdrant /collections via gateway with api-key" "http_status=$code $(elapsed)"
    else
      fail "curl Qdrant /collections via gateway with api-key" "http_status=$code url=$url"
    fi
    return
  fi

  local svc_name
  svc_name=$(kubectl -n "$NAMESPACE" get svc -l "app.kubernetes.io/instance" -o json 2>/dev/null \
    | jq -r ".items[] | select(.metadata.name | startswith(\"qdrant-\")) | select(.metadata.name | endswith(\"$( echo "$VECTORDB_INSTANCE_ID" | cut -c1-8)\")) | .metadata.name" | head -1)
  if [[ -z "$svc_name" ]]; then
    # fall back: any qdrant-* ClusterIP service in the namespace
    svc_name=$(kubectl -n "$NAMESPACE" get svc -o name 2>/dev/null | grep '^service/qdrant-' | grep -v -- '-headless' | head -1 | cut -d/ -f2)
  fi
  if [[ -z "$svc_name" ]]; then
    fail "curl Qdrant /healthz" "could not find qdrant service in namespace $NAMESPACE"
    return
  fi
  info "port-forwarding svc/$svc_name 16333:6333"
  kubectl -n "$NAMESPACE" port-forward "svc/$svc_name" 16333:6333 >/tmp/e2e-pf-qdrant.log 2>&1 &
  PF_PID=$!
  local ok=false
  for _ in $(seq 1 20); do
    if curl -sS -o /dev/null -w "" "http://localhost:16333/healthz" 2>/dev/null; then
      ok=true
      break
    fi
    sleep 1
  done
  if $ok; then
    local code
    code=$(curl -sS -o /dev/null -w "%{http_code}" "http://localhost:16333/healthz")
    if [[ "$code" == "200" ]]; then
      pass "curl Qdrant /healthz via port-forward" "http_status=$code $(elapsed)"
    else
      fail "curl Qdrant /healthz via port-forward" "http_status=$code"
    fi
  else
    fail "curl Qdrant /healthz via port-forward" "port-forward never became ready, see /tmp/e2e-pf-qdrant.log"
  fi
  stop_port_forward
}

step_delete_vectordb() {
  [[ -z "$VECTORDB_INSTANCE_ID" ]] && return
  api_delete "/v1alpha1/vectordb_instances/$VECTORDB_INSTANCE_ID"
  if [[ "$API_STATUS" != "204" && "$API_STATUS" != "200" ]]; then
    fail "DELETE /v1alpha1/vectordb_instances/{id}" "http_status=$API_STATUS"
    return
  fi
  local deadline=$(( $(date +%s) + 180 ))
  local gone=false
  while [[ $(date +%s) -lt $deadline ]]; do
    if ! helm -n "$NAMESPACE" list -o json 2>/dev/null | jq -e '.[] | select(.name | startswith("qdrant-"))' >/dev/null 2>&1; then
      gone=true
      break
    fi
    sleep 3
  done
  if $gone; then
    pass "vectordb Helm release removed" "$(elapsed)"
    VECTORDB_INSTANCE_ID=""
  else
    fail "vectordb Helm release removed" "still present after 180s"
  fi
}

# --- 4. jupyter notebook instance -----------------------------------------------

step_create_notebook() {
  api_post "/v1alpha1/notebooks" '{
          "name": "e2e-smoke",
          "namespace": "'"$NAMESPACE"'",
          "type": "jupyter",
          "framework": "pytorch",
          "nvidia_gpu": false,
          "resources_cpu": "0.5",
          "resources_memory": "1Gi",
          "storage_size": "1Gi",
          "service_type": "ClusterIP",
          "service_port": 80
        }'
  if [[ "$API_STATUS" != "200" && "$API_STATUS" != "201" ]]; then
    fail "POST /v1alpha1/notebooks" "http_status=$API_STATUS body=$(cat "$API_BODY_FILE")"
    return
  fi
  NOTEBOOK_INSTANCE_ID=$(jq -r '.id' "$API_BODY_FILE")
  pass "POST /v1alpha1/notebooks" "id=$NOTEBOOK_INSTANCE_ID $(elapsed)"
}

step_wait_notebook_ready() {
  [[ -z "$NOTEBOOK_INSTANCE_ID" ]] && { fail "wait for notebook instance Running" "no instance id (create failed)"; return; }
  local deadline=$(( $(date +%s) + 600 ))
  local endpoint="" status_val=""
  while [[ $(date +%s) -lt $deadline ]]; do
    api_get "/v1alpha1/notebooks/$NOTEBOOK_INSTANCE_ID"
    endpoint=$(jq -r '.endpoint // empty' "$API_BODY_FILE" 2>/dev/null || echo "")
    status_val=$(jq -r '.status // empty' "$API_BODY_FILE" 2>/dev/null || echo "")
    if [[ -n "$endpoint" && "$status_val" == "Running" ]]; then
      pass "notebook instance Running" "endpoint=$endpoint $(elapsed)"
      return
    fi
    sleep 5
  done
  fail "wait for notebook instance Running" "timed out after 10m (endpoint=$endpoint status=$status_val)"
}

step_notebook_curl() {
  [[ -z "$NOTEBOOK_INSTANCE_ID" ]] && { fail "curl notebook base path" "no instance id"; return; }

  # Behind the gateway, .endpoint is already the full https:// URL
  # (including the /notebook/<ns>/<svc>/lab path); curl it directly
  # instead of port-forwarding to the Service.
  local endpoint
  api_get "/v1alpha1/notebooks/$NOTEBOOK_INSTANCE_ID"
  endpoint=$(jq -r '.endpoint // empty' "$API_BODY_FILE" 2>/dev/null || echo "")
  if [[ "$endpoint" == https://* ]]; then
    # The Notebook reports Running before Jupyter listens on 8888, which
    # the gateway answers as a 503 (upstream connect error) until the pod
    # is actually accepting connections; retry like the port-forward path.
    local code attempt
    for attempt in $(seq 1 12); do
      code=$(curl -sS --cacert "$CA_CERT" -o /tmp/e2e-notebook-body.txt -w "%{http_code}" "$endpoint" || echo 000)
      [[ "$code" == "200" || "$code" == "302" || "$code" == "303" ]] && break
      sleep 5
    done
    if [[ "$code" == "200" || "$code" == "302" || "$code" == "303" ]]; then
      pass "curl notebook base path via gateway" "http_status=$code $(elapsed)"
    else
      fail "curl notebook base path via gateway" "http_status=$code body=$(head -c 200 /tmp/e2e-notebook-body.txt 2>/dev/null | tr '\n' ' ')"
    fi
    return
  fi

  local svc_name
  svc_name=$(kubectl -n "$NAMESPACE" get svc -o name 2>/dev/null | grep '^service/e2e-smoke-' | head -1 | cut -d/ -f2)
  if [[ -z "$svc_name" ]]; then
    fail "curl notebook base path" "could not find notebook service in namespace $NAMESPACE"
    return
  fi
  # The Notebook reports Running before Jupyter listens on 8888, and
  # kubectl port-forward exits on the first refused connection, so retry
  # with a fresh port-forward until Jupyter answers any HTTP status.
  local ok=false attempt
  for attempt in $(seq 1 12); do
    info "port-forwarding svc/$svc_name 18888:80 (attempt $attempt)"
    kubectl -n "$NAMESPACE" port-forward "svc/$svc_name" 18888:80 >/tmp/e2e-pf-notebook.log 2>&1 &
    PF_PID=$!
    sleep 2
    for _ in $(seq 1 5); do
      if curl -sS -o /dev/null "http://localhost:18888/" 2>/dev/null; then
        ok=true
        break
      fi
      sleep 1
    done
    $ok && break
    kill "$PF_PID" 2>/dev/null || true
    wait "$PF_PID" 2>/dev/null || true
    PF_PID=""
    sleep 5
  done
  if $ok; then
    local code
    # GET, not HEAD: Jupyter answers 405 to HEAD requests.
    code=$(curl -sS -o /tmp/e2e-notebook-body.txt -w "%{http_code}" "http://localhost:18888/notebook/$NAMESPACE/$svc_name/lab" || echo 000)
    if [[ "$code" == "200" || "$code" == "302" || "$code" == "303" ]]; then
      pass "curl notebook base path via port-forward" "http_status=$code $(elapsed)"
    else
      fail "curl notebook base path via port-forward" "http_status=$code body=$(head -c 200 /tmp/e2e-notebook-body.txt 2>/dev/null | tr '\n' ' ')"
    fi
  else
    fail "curl notebook base path via port-forward" "port-forward never became ready, see /tmp/e2e-pf-notebook.log"
  fi
  stop_port_forward
}

step_delete_notebook() {
  [[ -z "$NOTEBOOK_INSTANCE_ID" ]] && return
  api_delete "/v1alpha1/notebooks/$NOTEBOOK_INSTANCE_ID"
  if [[ "$API_STATUS" != "200" && "$API_STATUS" != "204" ]]; then
    fail "DELETE /v1alpha1/notebooks/{id}" "http_status=$API_STATUS"
    return
  fi
  local deadline=$(( $(date +%s) + 180 ))
  local gone=false
  while [[ $(date +%s) -lt $deadline ]]; do
    if ! helm -n "$NAMESPACE" list -o json 2>/dev/null | jq -e '.[] | select(.name | startswith("e2e-smoke-"))' >/dev/null 2>&1; then
      gone=true
      break
    fi
    sleep 3
  done
  if $gone; then
    pass "notebook Helm release removed" "$(elapsed)"
    NOTEBOOK_INSTANCE_ID=""
  else
    fail "notebook Helm release removed" "still present after 180s"
  fi
}

# --- Ollama: launch qwen3:0.6b and ask one question ---------------------------

step_create_ollama() {
  local model_id engine_id
  api_get "/v1alpha1/models"
  model_id=$(jq -r '.[] | select(.modelId == "qwen3:0.6b") | .id' "$API_BODY_FILE" | head -1)
  api_get "/v1alpha1/engines"
  engine_id=$(jq -r '.[] | select(.name == "Ollama") | .id' "$API_BODY_FILE" | head -1)
  if [[ -z "$model_id" || -z "$engine_id" || "$model_id" == "null" || "$engine_id" == "null" ]]; then
    fail "resolve qwen3:0.6b and the Ollama engine" "model=$model_id engine=$engine_id"
    return
  fi
  info "qwen3:0.6b catalog id: $model_id, Ollama engine id: $engine_id"

  api_post "/v1alpha1/inferenceInstance" \
    "{\"model\":{\"id\":\"$model_id\"},\"engine\":{\"id\":\"$engine_id\"},\"config\":{}}"
  if [[ "$API_STATUS" != "201" ]]; then
    fail "POST /v1alpha1/inferenceInstance (Ollama)" "http_status=$API_STATUS body=$(cat "$API_BODY_FILE")"
    return
  fi
  INFERENCE_INSTANCE_ID=$(jq -r '.id' "$API_BODY_FILE")
  pass "POST /v1alpha1/inferenceInstance (Ollama qwen3:0.6b)" "id=$INFERENCE_INSTANCE_ID $(elapsed)"
}

step_wait_ollama_ready() {
  [[ -z "$INFERENCE_INSTANCE_ID" ]] && { fail "wait for Ollama instance Ready" "no instance id (create failed)"; return; }
  # The first run pulls the 2.6 GiB Ollama image and the model.
  local deadline=$(( $(date +%s) + 900 ))
  local endpoint="" ready="false"
  while [[ $(date +%s) -lt $deadline ]]; do
    api_get "/v1alpha1/inferenceInstance/$INFERENCE_INSTANCE_ID"
    endpoint=$(jq -r '.endpoint // empty' "$API_BODY_FILE" 2>/dev/null || echo "")
    ready=$(jq -r '.ready // false' "$API_BODY_FILE" 2>/dev/null || echo "false")
    if [[ -n "$endpoint" && "$ready" == "true" ]]; then
      pass "Ollama instance Ready" "endpoint=$endpoint $(elapsed)"
      return
    fi
    sleep 10
  done
  fail "wait for Ollama instance Ready" "timed out after 15m (endpoint=$endpoint ready=$ready)"
}

# The chat target is the instance's LiteLLM name (inst-<id8>, also used
# without LiteLLM); the backend replaces it with the engine's model id when
# it forwards directly.
instance_target() {
  api_get "/v1alpha1/inferenceInstance/$1"
  local name
  name=$(jq -r '.litellm_model_name // empty' "$API_BODY_FILE" 2>/dev/null || echo "")
  [[ -n "$name" ]] && { echo "$name"; return; }
  local hex="${1//-/}"
  echo "inst-${hex: -8}"
}

step_chat_completion() {
  [[ -z "$INFERENCE_INSTANCE_ID" ]] && { fail "POST /v1alpha1/chat/completions" "no instance id"; return; }
  local target
  target=$(instance_target "$INFERENCE_INSTANCE_ID")
  info "chat target: $target"
  api_post "/v1alpha1/chat/completions" \
    "{\"model\":\"$target\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word pong.\"}],\"stream\":false,\"max_tokens\":400}"
  # qwen3 thinks first; when the budget goes to reasoning, the answer is
  # in message.reasoning and content stays empty. Either proves the path.
  local content
  content=$(jq -r '.choices[0].message.content // .choices[0].message.reasoning // .choices[0].message.reasoning_content // empty' "$API_BODY_FILE" 2>/dev/null || echo "")
  if [[ "$API_STATUS" == "200" && -n "$content" ]]; then
    pass "POST /v1alpha1/chat/completions" "answer=$(echo "$content" | head -c 60 | tr '\n' ' ') $(elapsed)"
  else
    fail "POST /v1alpha1/chat/completions" "http_status=$API_STATUS body=$(head -c 300 "$API_BODY_FILE")"
  fi
}

step_delete_ollama() {
  [[ -z "$INFERENCE_INSTANCE_ID" ]] && return
  api_delete "/v1alpha1/inferenceInstance/$INFERENCE_INSTANCE_ID"
  if [[ "$API_STATUS" == "200" ]]; then
    pass "DELETE /v1alpha1/inferenceInstance/$INFERENCE_INSTANCE_ID" "$(elapsed)"
    INFERENCE_INSTANCE_ID=""
  else
    fail "DELETE /v1alpha1/inferenceInstance/$INFERENCE_INSTANCE_ID" "http_status=$API_STATUS"
  fi
}

# --- Ollama embeddings through LiteLLM ---------------------------------------

step_create_embedding_instance() {
  local model_id engine_id
  api_get "/v1alpha1/models"
  model_id=$(jq -r '.[] | select(.modelId == "all-minilm:33m") | .id' "$API_BODY_FILE" | head -1)
  api_get "/v1alpha1/engines"
  engine_id=$(jq -r '.[] | select(.name == "Ollama") | .id' "$API_BODY_FILE" | head -1)
  if [[ -z "$model_id" || -z "$engine_id" || "$model_id" == "null" || "$engine_id" == "null" ]]; then
    fail "resolve all-minilm:33m and the Ollama engine" "model=$model_id engine=$engine_id"
    return
  fi
  api_post "/v1alpha1/inferenceInstance" \
    "{\"model\":{\"id\":\"$model_id\"},\"engine\":{\"id\":\"$engine_id\"},\"config\":{}}"
  if [[ "$API_STATUS" != "201" ]]; then
    fail "POST /v1alpha1/inferenceInstance (Ollama embeddings)" "http_status=$API_STATUS body=$(cat "$API_BODY_FILE")"
    return
  fi
  INFERENCE_INSTANCE_ID=$(jq -r '.id' "$API_BODY_FILE")
  pass "POST /v1alpha1/inferenceInstance (Ollama all-minilm:33m)" "id=$INFERENCE_INSTANCE_ID $(elapsed)"
}

step_embeddings() {
  [[ -z "$INFERENCE_INSTANCE_ID" ]] && { fail "POST /v1alpha1/embeddings" "no instance id"; return; }
  local target dims
  target=$(instance_target "$INFERENCE_INSTANCE_ID")
  api_post "/v1alpha1/embeddings" "{\"model\":\"$target\",\"input\":[\"hello world\"]}"
  dims=$(jq -r '.data[0].embedding | length' "$API_BODY_FILE" 2>/dev/null || echo "0")
  if [[ "$API_STATUS" == "200" && "$dims" -gt 0 ]]; then
    pass "POST /v1alpha1/embeddings" "dims=$dims $(elapsed)"
  elif [[ "$API_STATUS" == "503" ]]; then
    fail "POST /v1alpha1/embeddings" "503: LiteLLM is not configured (make litellm-up, then restart make backend)"
  else
    fail "POST /v1alpha1/embeddings" "http_status=$API_STATUS body=$(head -c 300 "$API_BODY_FILE")"
  fi
}

# --- run ---------------------------------------------------------------------

echo "== aiops-platform e2e smoke test =="
echo "BACKEND_URL=$BACKEND_URL NAMESPACE=$NAMESPACE AUTH_MODE=$AUTH_MODE SKIP_NOTEBOOK=$SKIP_NOTEBOOK SKIP_OLLAMA=$SKIP_OLLAMA"
echo ""

if [[ "$AUTH_MODE" != "disabled" ]]; then
  info "fetching an automation token from $OIDC_ISSUER"
  fetch_token
fi

step_health
step_catalog "/v1alpha1/vectordb" "vectordb catalog"
step_catalog "/v1alpha1/models" "models catalog"
step_catalog "/v1alpha1/engines" "engines catalog"

step_create_vectordb
step_wait_vectordb_ready
step_qdrant_healthz
step_delete_vectordb

if ! $SKIP_NOTEBOOK; then
  step_create_notebook
  step_wait_notebook_ready
  step_notebook_curl
  step_delete_notebook
else
  echo "SKIP  notebook steps (--skip-notebook)"
fi

if ! $SKIP_OLLAMA; then
  step_create_ollama
  step_wait_ollama_ready
  step_chat_completion
  step_delete_ollama
  step_create_embedding_instance
  step_wait_ollama_ready
  step_embeddings
  step_delete_ollama
else
  echo "SKIP  ollama steps (--skip-ollama)"
fi

echo ""
echo "== summary =="
if [[ "$FAILURES" -eq 0 ]]; then
  echo "ALL STEPS PASSED ($(elapsed) total)"
  exit 0
else
  echo "$FAILURES step(s) FAILED ($(elapsed) total)"
  exit 1
fi
