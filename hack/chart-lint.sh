#!/usr/bin/env bash
# Lint and render checks for charts/aiops-platform (make chart-lint):
#   helm lint --strict with the default values and the external and gpu-node fixtures,
#   helm template with the default, external, kind and gpu-node values, and
#   assertions on what each render must and must not contain.
# Requires: helm (and network for helm dependency build).
set -euo pipefail
cd "$(dirname "$0")/.."

CHART=charts/aiops-platform
FAILURES=0

pass() { printf "PASS  %s\n" "$1"; }
fail() { printf "FAIL  %s\n" "$1" >&2; FAILURES=$((FAILURES + 1)); }
# expect <name> <extended regex> <text>: the text matches.
# Not grep -q: under pipefail an early match makes grep exit while printf is
# still writing a render larger than the pipe buffer, and the SIGPIPE turns
# a match into a failure. Reading to the end has no such race.
expect() { if printf '%s' "$3" | grep -E -- "$2" >/dev/null; then pass "$1"; else fail "$1"; fi; }
# reject <name> <extended regex> <text>: the text does not match.
reject() { if printf '%s' "$3" | grep -E -- "$2" >/dev/null; then fail "$1"; else pass "$1"; fi; }

helm dependency build "$CHART" >/dev/null
helm lint --strict "$CHART"
helm lint --strict "$CHART" -f "$CHART/test/values-external.yaml"
helm lint --strict "$CHART" -f "$CHART/test/values-gpu-node.yaml"

default=$(helm template aiops-platform "$CHART" -n aiops-platform)
external=$(helm template aiops-platform "$CHART" -n aiops-platform -f "$CHART/test/values-external.yaml")
kind_render=$(helm template aiops-platform "$CHART" -n aiops-platform -f "$CHART/test/values-kind.yaml")
gpu_render=$(helm template aiops-platform "$CHART" -n aiops-platform -f "$CHART/test/values-gpu-node.yaml")
# test/values-kind.yaml is also the make chart-install fixture and keeps
# Langflow off (a second 2 GB image next to the dev Langflow); this render
# turns it on the way chart-install would.
langflow_render=$(helm template aiops-platform "$CHART" -n aiops-platform -f "$CHART/test/values-kind.yaml" \
  --set langflow.enabled=true --set global.caSecret=aiops-platform-ca \
  --set-json 'langflow.hostAliases=[{"ip":"10.96.0.10","hostnames":["auth.platform.127.0.0.1.nip.io"]}]')
# Langflow of the operator's own, embedded and provisioned through its public address.
external_langflow=$(helm template aiops-platform "$CHART" -n aiops-platform -f "$CHART/test/values-external.yaml" \
  --set ui.langflowUrl=https://langflow.example.com)
# The AI Factory Explorer is off by default; render it on, and once without
# the gateway (the Service and the Deployment do not need a route).
viz_render=$(helm template aiops-platform "$CHART" -n aiops-platform --set viz.enabled=true)
viz_no_gateway=$(helm template aiops-platform "$CHART" -n aiops-platform --set viz.enabled=true --set gateway.enabled=false)

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
expect "the backend tells flows where the MCP endpoint is" 'AIOPS_BACKEND_CLUSTER_URL: "http://aiops-platform-backend:8000"' "$(helm template aiops-platform "$CHART" -n aiops-platform --set langflow.enabled=true -s templates/backend/configmap.yaml)"
expect "the backend knows the UI address for OAuth callbacks" 'AIOPS_UI_URL: "https://ui\.aiops\.example\.com"' "$default"
expect "the backend may create the policy of a deployed MCP server" 'resources: \["networkpolicies"\]' "$default"
expect "the backend knows the proxy's pods" 'AIOPS_LITELLM_POD_LABELS: "app.kubernetes.io/name=litellm,app.kubernetes.io/instance=aiops-platform"' "$default"
expect "the backend knows the proxy's namespace" 'AIOPS_LITELLM_NAMESPACE: "aiops-platform"' "$default"
expect "import from the MCP registry is on by default" 'AIOPS_MCP_REGISTRY_URL: "https://registry\.modelcontextprotocol\.io"' "$default"
expect "an empty registry URL is rendered, so import is off" 'AIOPS_MCP_REGISTRY_URL: ""' "$(helm template aiops-platform "$CHART" -n aiops-platform --set backend.mcp.registryUrl= -s templates/backend/configmap.yaml)"
reject "default renders no egress policy for the proxy" 'name: aiops-litellm-egress$' "$default"
egress=$(helm template aiops-platform "$CHART" -n aiops-platform --set litellm.egressPolicy.enabled=true \
  --set 'litellm.egressPolicy.allowCIDRs={10.0.5.12/32}' -s templates/litellm/networkpolicy.yaml)
expect "the proxy's egress policy selects the proxy pods" 'app.kubernetes.io/name: litellm$' "$egress"
expect "the proxy's egress policy leaves private addresses out of the public rule" '- "169\.254\.0\.0/16"$' "$egress"
expect "the proxy's egress policy allows a named private address" 'cidr: "10\.0\.5\.12/32"$' "$egress"
expect "the proxy's egress policy allows https only by default" 'port: 443$' "$egress"
traffic=$(helm template aiops-platform "$CHART" -n aiops-platform -s templates/gateway/backendtrafficpolicy.yaml)
expect "the api route has the stream timeout too (MCP sessions)" 'name: aiops-platform-api$' "$traffic"
expect "default fails the release when a policy is not accepted" 'until accepted "\$policy"' "$default"
expect "the policy check waits ten minutes by default" '"\$tries" -ge 300 ' "$default"
expect "the policy check may read policies" 'resources: \["securitypolicies"\]' "$default"
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

# --- the AI Factory Explorer (viz.enabled) --------------------------------------
reject "default renders no explorer" 'name: aiops-platform-viz$' "$default"
expect "viz renders its Deployment and Service" 'name: aiops-platform-viz$' "$viz_render"
expect "viz serves the explorer image" 'image: "ghcr\.io/infracloudio/ai-factory-explorer:main"' "$viz_render"
expect "viz runs the unprivileged nginx port" 'containerPort: 8080' "$viz_render"
expect "viz routes the viz host" '"viz\.aiops\.example\.com"' "$viz_render"
expect "viz is a ClusterIP Service" 'type: ClusterIP' "$viz_render"
reject "viz without the gateway renders no route" '"viz\.aiops\.example\.com"' "$viz_no_gateway"
expect "viz without the gateway still deploys" 'name: aiops-platform-viz$' "$viz_no_gateway"
expect "viz takes its own image tag" 'image: "ghcr\.io/infracloudio/ai-factory-explorer:abc1234"' \
  "$(helm template aiops-platform "$CHART" -n aiops-platform --set viz.enabled=true --set viz.image.tag=abc1234)"

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

# --- gpu-node fixture: one node, own GatewayClass, private CA, model cache ------
reject "default renders no hf-cache claim" 'name: hf-cache$' "$default"
expect "gpu-node renders the hf-cache claim" 'name: hf-cache$' "$gpu_render"
expect "gpu-node hf-cache claim uses the node's StorageClass" 'storageClassName: "local-path"' "$gpu_render"
expect "gpu-node hf-cache claim survives uninstall" 'helm.sh/resource-policy: keep' "$gpu_render"
expect "gpu-node renders a Gateway" '^kind: Gateway$' "$gpu_render"
expect "gpu-node Gateway uses its own GatewayClass" 'gatewayClassName: "?aiops"?$' "$gpu_render"
expect "gpu-node Gateway terminates with the wildcard Secret" 'name: "?aiops-wildcard-tls"?$' "$gpu_render"
expect "gpu-node Certificate is issued by the private CA" 'name: aiops-ca$' "$gpu_render"
expect "gpu-node routes the ui host" '"ui\.aiops\.example\.com"' "$gpu_render"
expect "gpu-node mounts the CA Secret" 'secretName: "?aiops-ca"?$' "$gpu_render"
expect "gpu-node serves the Grafana URL to the UI" 'GRAFANA_URL: "https://grafana\.aiops\.example\.com"' "$gpu_render"
expect "gpu-node deploys Langflow" 'name: aiops-platform-langflow$' "$gpu_render"
expect "gpu-node UI embeds the bundled Langflow" 'LANGFLOW_URL: "https://langflow\.aiops\.example\.com"' "$gpu_render"
expect "gpu-node API pod reads the model cache" 'MODEL_CACHE_DIR: "/model-cache"' "$gpu_render"
expect "gpu-node mounts the model cache read-only" 'claimName: hf-cache' "$gpu_render"
reject "default API pod has no model cache mount" 'model-cache' "$default"
expect "gpu-node sets the short vLLM liveness delay" 'VLLM_LIVENESS_INITIAL_DELAY_SECONDS: "60"' "$gpu_render"
reject "gpu-node realm has no dev users" '"username": "alice"' "$gpu_render"
expect "gpu-node limits the proxy's outgoing connections" 'name: aiops-litellm-egress$' "$gpu_render"

# --- Langflow ------------------------------------------------------------------
reject "the default render has no Langflow" 'aiops-platform-langflow' "$default"
expect "Langflow's volume is writable for its user" 'fsGroup: 1000$' "$langflow_render"
expect "the Langflow render deploys it" 'name: aiops-platform-langflow$' "$langflow_render"
expect "Langflow's policy forwards the token and passes a bearer through" 'passThroughAuthHeader: true' "$langflow_render"
expect "pass-through comes with Envoy's own JWT check" 'name: keycloak$' "$langflow_render"
expect "Langflow verifies against the public https JWKS" 'value: "https://auth\.platform\.127\.0\.0\.1\.nip\.io/realms/aiops/protocol/openid-connect/certs"' "$langflow_render"
# Unquoted: toYaml renders hostAliases' hostnames bare, while route
# hostnames are quoted, so this line can only be the pod's alias.
expect "the pod aliases the auth host" '^ +- auth\.platform\.127\.0\.0\.1\.nip\.io$' "$langflow_render"
expect "the realm registers the Langflow callback" 'langflow\.platform\.127\.0\.0\.1\.nip\.io/oauth2/callback' "$langflow_render"
expect "the backend knows Langflow's Service" 'LANGFLOW_API_URL: "http://aiops-platform-langflow:7860"' "$langflow_render"
reject "the chart sets no LITELLM_CLUSTER_URL (LITELLM_URL is already the Service)" 'LITELLM_CLUSTER_URL' "$langflow_render"
expect "Langflow may reach LiteLLM (models) and the backend (tools, /v1alpha1/mcp) only" 'value: "aiops-litellm,aiops-platform-backend"$' "$langflow_render"
expect "the policy check waits on Langflow's policy too" 'aiops-workloads-oidc aiops-platform-langflow-oidc' "$langflow_render"
expect "both policies share one ext-authz path" '^2$' "$(printf '%s' "$langflow_render" | grep -c -- 'path: /v1alpha1/authz/route')"
expect "an external Langflow gets the same API address" 'LANGFLOW_API_URL: "https://langflow\.example\.com"' "$external_langflow"
if helm template aiops-platform "$CHART" -n aiops-platform --set langflow.enabled=true --set gateway.enabled=false >/dev/null 2>&1; then
  fail "langflow.enabled without gateway.enabled is refused"
else
  pass "langflow.enabled without gateway.enabled is refused"
fi
expect "the UI embeds the bundled Langflow" 'LANGFLOW_URL: "https://langflow\.platform\.127\.0\.0\.1\.nip\.io"' "$langflow_render"
expect "the superuser password comes from the platform Secret" 'key: LANGFLOW_SUPERUSER_PASSWORD$' "$langflow_render"
expect "the hook generates the superuser password" 'LANGFLOW_SUPERUSER_PASSWORD\) rand 32' "$default"

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
reject "no dev literal in any render" 'dev-gateway-secret|dev-automation-secret|sk-dev-litellm-master|dev-auth-secret-change-me|changeme' "$default$external$kind_render$langflow_render$gpu_render"

# --- charts/mcp-server: one MCP server the platform deploys ---------------------
MCP_CHART=charts/mcp-server
MCP_VALUES="$MCP_CHART/ci/lint-values.yaml"
helm lint --strict "$MCP_CHART" -f "$MCP_VALUES"
mcp=$(helm template mcpi-1234abcd "$MCP_CHART" -n ai-stack -f "$MCP_VALUES")
mcp_policy=$(helm template mcpi-1234abcd "$MCP_CHART" -n ai-stack -f "$MCP_VALUES" -s templates/networkpolicy.yaml)
expect "mcp-server mounts no service-account token" 'automountServiceAccountToken: false' "$mcp"
expect "mcp-server runs as non-root" 'runAsNonRoot: true' "$mcp"
expect "mcp-server has a read-only root file system" 'readOnlyRootFilesystem: true' "$mcp"
expect "mcp-server drops every capability" 'drop: \["ALL"\]|- ALL' "$mcp"
expect "mcp-server forbids privilege escalation" 'allowPrivilegeEscalation: false' "$mcp"
expect "mcp-server is a ClusterIP Service" 'type: ClusterIP' "$mcp"
reject "mcp-server has no LoadBalancer or NodePort" 'type: (LoadBalancer|NodePort)' "$mcp"
expect "mcp-server names the Service after the release" '^  name: mcpi-1234abcd$' "$mcp"
# ONE ingress element with both selectors (an AND). A second list element
# would be an OR and admit every pod of the proxy's namespace.
expect "mcp-server ingress names the proxy's namespace" '^        - namespaceSelector:$' "$mcp_policy"
expect "mcp-server ingress names the proxy's pods in the same element" '^          podSelector:$' "$mcp_policy"
reject "mcp-server ingress has no second element for pods" '^        - podSelector:' "$mcp_policy"
expect "mcp-server ingress is for the proxy's labels" 'app.kubernetes.io/name: litellm' "$mcp_policy"
expect "mcp-server egress always allows DNS" 'port: 53' "$mcp_policy"
expect "mcp-server public egress leaves out the private ranges" '- "10.0.0.0/8"' "$mcp_policy"
expect "mcp-server public egress leaves out the metadata range" '- "169.254.0.0/16"' "$mcp_policy"
reject "mcp-server public egress opens no private range" 'cidr: "10.0.0.0/8"' "$mcp_policy"
mcp_cluster=$(helm template mcpi-1234abcd "$MCP_CHART" -f "$MCP_VALUES" --set networkPolicy.egress=cluster -s templates/networkpolicy.yaml)
expect "mcp-server cluster egress opens the private ranges" 'cidr: "10.0.0.0/8"' "$mcp_cluster"
reject "mcp-server cluster egress never opens the metadata range" 'cidr: "169.254.0.0/16"' "$mcp_cluster"
mcp_none=$(helm template mcpi-1234abcd "$MCP_CHART" -f "$MCP_VALUES" --set networkPolicy.egress=none -s templates/networkpolicy.yaml)
reject "mcp-server egress none opens nothing but DNS" 'ipBlock' "$mcp_none"
expect "mcp-server refuses to render without the ingress rule" 'ingressFrom.namespace is required' "$(helm template x "$MCP_CHART" --set image.repository=a/b --set image.tag=1 2>&1 || true)"
expect "mcp-server refuses the tag latest" 'must not be latest' "$(helm template x "$MCP_CHART" -f "$MCP_VALUES" --set image.tag=latest 2>&1 || true)"
expect "mcp-server takes a digest" 'image: "mcp/grafana@sha256:abc"' "$(helm template x "$MCP_CHART" -f "$MCP_VALUES" --set image.tag=@sha256:abc)"
expect "mcp-server rolls the pod on a settings change" 'checksum/settings: "abc123"' "$(helm template x "$MCP_CHART" -f "$MCP_VALUES" --set settingsChecksum=abc123)"

if (( FAILURES > 0 )); then
  echo "$FAILURES check(s) failed" >&2
  exit 1
fi
echo "All chart checks passed."
