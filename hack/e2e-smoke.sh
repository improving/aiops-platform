#!/usr/bin/env bash
# End-to-end smoke test for the aiops-platform local dev stack.
#
# Exercises the backend control-plane API against a real kind cluster:
#   - health check
#   - catalog listings (vectordb, models, engines)
#   - create a Qdrant vector DB instance, wait for it to be Ready, curl its
#     health endpoint through a port-forward
#   - create a Jupyter notebook instance, wait for it to be Running, curl its
#     base path through a port-forward (skip with --skip-notebook)
#   - delete both instances and wait for their Helm releases to disappear
#
# Requires: curl, jq, kubectl. Run via `make e2e-smoke` or directly.
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
NAMESPACE="${NAMESPACE:-ai-stack}"
SKIP_NOTEBOOK=false

for arg in "$@"; do
  case "$arg" in
    --skip-notebook) SKIP_NOTEBOOK=true ;;
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
PF_PID=""

pass() { printf "PASS  %-55s %s\n" "$1" "${2:-}"; }
fail() { printf "FAIL  %-55s %s\n" "$1" "${2:-}"; FAILURES=$((FAILURES + 1)); }
info() { printf "INFO  %s\n" "$1"; }

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
    curl -sS -X DELETE "$BACKEND_URL/v1alpha1/vectordb_instances/$VECTORDB_INSTANCE_ID" \
      -o /dev/null -w "" || true
  fi
  if [[ -n "$NOTEBOOK_INSTANCE_ID" ]]; then
    info "cleanup: deleting notebook instance $NOTEBOOK_INSTANCE_ID"
    curl -sS -X DELETE "$BACKEND_URL/v1alpha1/notebooks/$NOTEBOOK_INSTANCE_ID" \
      -o /dev/null -w "" || true
  fi
}
trap cleanup EXIT

start_ts=$(date +%s)
elapsed() { echo "$(( $(date +%s) - start_ts ))s"; }

# --- 1. health ---------------------------------------------------------------

step_health() {
  local body status
  body=$(curl -sS -o /tmp/e2e-health.json -w "%{http_code}" "$BACKEND_URL/health") || true
  if [[ "$body" == "200" ]] && [[ "$(jq -r '.message' /tmp/e2e-health.json 2>/dev/null)" == "OK" ]]; then
    pass "GET /health" "$(elapsed)"
  else
    fail "GET /health" "http_status=$body body=$(cat /tmp/e2e-health.json 2>/dev/null)"
  fi
}

# --- 2. catalogs ---------------------------------------------------------------

step_catalog() {
  local path="$1" label="$2"
  local count
  count=$(curl -sS "$BACKEND_URL$path" | jq 'length' 2>/dev/null || echo 0)
  if [[ "$count" -gt 0 ]]; then
    pass "GET $path ($label)" "count=$count $(elapsed)"
  else
    fail "GET $path ($label)" "count=$count"
  fi
}

# --- 3. qdrant vectordb instance ------------------------------------------------

step_create_vectordb() {
  local qdrant_id
  qdrant_id=$(curl -sS "$BACKEND_URL/v1alpha1/vectordb" | jq -r '.[] | select(.name == "Qdrant") | .id' | head -1)
  if [[ -z "$qdrant_id" || "$qdrant_id" == "null" ]]; then
    fail "resolve Qdrant catalog id" "not found in /v1alpha1/vectordb"
    return
  fi
  info "Qdrant catalog id: $qdrant_id"

  local resp status
  resp=$(curl -sS -o /tmp/e2e-vectordb-create.json -w "%{http_code}" \
    -X POST "$BACKEND_URL/v1alpha1/vectordb_instances" \
    -H "Content-Type: application/json" \
    -d "{\"vectorDB\":{\"id\":\"$qdrant_id\"},\"configParams\":{\"serviceType\":\"ClusterIP\"}}")
  status="$resp"
  if [[ "$status" != "201" ]]; then
    fail "POST /v1alpha1/vectordb_instances" "http_status=$status body=$(cat /tmp/e2e-vectordb-create.json)"
    return
  fi
  VECTORDB_INSTANCE_ID=$(jq -r '.id' /tmp/e2e-vectordb-create.json)
  pass "POST /v1alpha1/vectordb_instances" "id=$VECTORDB_INSTANCE_ID $(elapsed)"
}

step_wait_vectordb_ready() {
  [[ -z "$VECTORDB_INSTANCE_ID" ]] && { fail "wait for vectordb instance Ready" "no instance id (create failed)"; return; }
  local deadline=$(( $(date +%s) + 600 ))
  local endpoint="" ready="false"
  while [[ $(date +%s) -lt $deadline ]]; do
    local body
    body=$(curl -sS "$BACKEND_URL/v1alpha1/vectordb_instances/$VECTORDB_INSTANCE_ID" || echo '{}')
    endpoint=$(jq -r '.endpoint // empty' <<<"$body")
    ready=$(jq -r '.ready // false' <<<"$body")
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
  local status
  status=$(curl -sS -o /dev/null -w "%{http_code}" -X DELETE "$BACKEND_URL/v1alpha1/vectordb_instances/$VECTORDB_INSTANCE_ID")
  if [[ "$status" != "204" && "$status" != "200" ]]; then
    fail "DELETE /v1alpha1/vectordb_instances/{id}" "http_status=$status"
    return
  fi
  local deadline=$(( $(date +%s) + 120 ))
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
    fail "vectordb Helm release removed" "still present after 120s"
  fi
}

# --- 4. jupyter notebook instance -----------------------------------------------

step_create_notebook() {
  local resp status
  resp=$(curl -sS -o /tmp/e2e-notebook-create.json -w "%{http_code}" \
    -X POST "$BACKEND_URL/v1alpha1/notebooks" \
    -H "Content-Type: application/json" \
    -d '{
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
        }')
  status="$resp"
  if [[ "$status" != "200" && "$status" != "201" ]]; then
    fail "POST /v1alpha1/notebooks" "http_status=$status body=$(cat /tmp/e2e-notebook-create.json)"
    return
  fi
  NOTEBOOK_INSTANCE_ID=$(jq -r '.id' /tmp/e2e-notebook-create.json)
  pass "POST /v1alpha1/notebooks" "id=$NOTEBOOK_INSTANCE_ID $(elapsed)"
}

step_wait_notebook_ready() {
  [[ -z "$NOTEBOOK_INSTANCE_ID" ]] && { fail "wait for notebook instance Running" "no instance id (create failed)"; return; }
  local deadline=$(( $(date +%s) + 600 ))
  local endpoint="" status_val=""
  while [[ $(date +%s) -lt $deadline ]]; do
    local body
    body=$(curl -sS "$BACKEND_URL/v1alpha1/notebooks/$NOTEBOOK_INSTANCE_ID" || echo '{}')
    endpoint=$(jq -r '.endpoint // empty' <<<"$body")
    status_val=$(jq -r '.status // empty' <<<"$body")
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
  local status
  status=$(curl -sS -o /dev/null -w "%{http_code}" -X DELETE "$BACKEND_URL/v1alpha1/notebooks/$NOTEBOOK_INSTANCE_ID")
  if [[ "$status" != "200" && "$status" != "204" ]]; then
    fail "DELETE /v1alpha1/notebooks/{id}" "http_status=$status"
    return
  fi
  local deadline=$(( $(date +%s) + 120 ))
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
    fail "notebook Helm release removed" "still present after 120s"
  fi
}

# --- run ---------------------------------------------------------------------

echo "== aiops-platform e2e smoke test =="
echo "BACKEND_URL=$BACKEND_URL NAMESPACE=$NAMESPACE SKIP_NOTEBOOK=$SKIP_NOTEBOOK"
echo ""

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

echo ""
echo "== summary =="
if [[ "$FAILURES" -eq 0 ]]; then
  echo "ALL STEPS PASSED ($(elapsed) total)"
  exit 0
else
  echo "$FAILURES step(s) FAILED ($(elapsed) total)"
  exit 1
fi
