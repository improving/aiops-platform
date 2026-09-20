SHELL := /bin/bash

.PHONY: help prereqs kind-up kind-down db-up db-down lb backend frontend e2e-smoke ui-e2e ui-e2e-cluster dev \
	gateway-up gateway-down ca-export trust-ca auth-up auth-down

# --- Variables ----------------------------------------------------------

CLUSTER_NAME       ?= aiops
NAMESPACE          ?= ai-stack
BACKEND_URL        ?= http://localhost:8000
FRONTEND_URL       ?= http://localhost:3000
KIND_CONFIG        := infra/local/kind-config.yaml
COMPOSE_FILE       := infra/local/docker-compose.yml
GATEWAY_DIR        := infra/local/gateway
CA_DIR             := infra/local/ca
CA_CRT             := $(CA_DIR)/ca.crt
GATEWAY_NAMESPACE  := envoy-gateway-system
CERT_MANAGER_NS    := cert-manager
AUTH_DIR           := infra/local/auth
AUTH_NAMESPACE     := auth
LANGFLOW_URL       ?= https://langflow.127.0.0.1.nip.io
AUTH_MODE          ?= oidc
OIDC_ISSUER        ?= https://auth.127.0.0.1.nip.io/realms/aiops
AUTH_SECRET        ?= dev-auth-secret-change-me
KEYCLOAK_ISSUER    ?= https://auth.127.0.0.1.nip.io/realms/aiops
NOTEBOOK_CTRL_REF  ?= v1.11.0
NOTEBOOK_CTRL_NS   := notebook-controller-system
NOTEBOOK_CTRL_DEPL := notebook-controller-deployment

# --- help (default) ------------------------------------------------------

help: ## Show this help
	@echo "aiops-platform local dev stack"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "See docs/local-dev.md for the full walkthrough."

# --- prereqs --------------------------------------------------------------

prereqs: ## Check required local tools are installed
	@missing=0; \
	for bin in kind helm kubectl uv pnpm colima docker; do \
		if command -v $$bin >/dev/null 2>&1; then \
			printf "  [ok]      %s (%s)\n" "$$bin" "$$(command -v $$bin)"; \
		else \
			printf "  [missing] %s\n" "$$bin"; \
			missing=1; \
		fi; \
	done; \
	if command -v kubeconform >/dev/null 2>&1; then \
		printf "  [ok]      kubeconform (optional, hack/lab-dry-run.sh)\n"; \
	else \
		printf "  [info]    kubeconform not found (optional, only hack/lab-dry-run.sh needs it)\n"; \
	fi; \
	if command -v colima >/dev/null 2>&1; then \
		if colima status >/dev/null 2>&1; then \
			printf "  [ok]      colima is running\n"; \
		else \
			printf "  [warn]    colima is installed but not running -- run 'colima start'\n"; \
		fi; \
	fi; \
	if ! command -v cloud-provider-kind >/dev/null 2>&1; then \
		printf "  [info]    cloud-provider-kind not installed (optional, see 'make lb')\n"; \
	fi; \
	exit $$missing

# --- kind cluster ----------------------------------------------------------

kind-up: ## Create the kind cluster (if absent), install notebook-controller, create the namespace
	@if kind get clusters 2>/dev/null | grep -qx "$(CLUSTER_NAME)"; then \
		echo "kind cluster '$(CLUSTER_NAME)' already exists"; \
		if ! docker port $(CLUSTER_NAME)-control-plane 2>/dev/null | grep -qE ':(80|443)$$'; then \
			echo "kind cluster '$(CLUSTER_NAME)' is missing the gateway port mappings (host 80/443)."; \
			echo "It was created before infra/local/kind-config.yaml added extraPortMappings."; \
			echo "Run 'make kind-down kind-up' to recreate it with the mappings."; \
			exit 1; \
		fi; \
	else \
		kind create cluster --config $(KIND_CONFIG); \
	fi
	kubectl config use-context kind-$(CLUSTER_NAME)
	kubectl create namespace $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -
	@# Colima's Lima VM defaults fs.inotify.max_user_instances to 128, which is too
	@# low for kubelet + containerd + the notebook-controller manager to all watch
	@# files at once (see infra/local/notebook-controller.md). Bump it every time;
	@# it does not persist across colima restarts and this is a no-op if already set.
	@if command -v colima >/dev/null 2>&1 && colima status >/dev/null 2>&1; then \
		colima ssh -- sudo sysctl -w fs.inotify.max_user_instances=8192 >/dev/null; \
		colima ssh -- sudo sysctl -w fs.inotify.max_user_watches=1048576 >/dev/null; \
	fi
	kubectl apply -k "github.com/kubeflow/notebooks/components/notebook-controller/config/overlays/standalone?ref=$(NOTEBOOK_CTRL_REF)"
	kubectl -n $(NOTEBOOK_CTRL_NS) wait --for=condition=Available \
		deployment/$(NOTEBOOK_CTRL_DEPL) --timeout=180s
	@echo "kind cluster '$(CLUSTER_NAME)' ready, namespace '$(NAMESPACE)' created, notebook-controller Available"

kind-down: ## Delete the kind cluster
	kind delete cluster --name $(CLUSTER_NAME)

# --- gateway and local TLS ---------------------------------------------------

gateway-up: ## Install Envoy Gateway + cert-manager and apply the local Gateway/TLS manifests (idempotent)
	helm upgrade --install eg oci://docker.io/envoyproxy/gateway-helm \
		--version v1.9.1 -n $(GATEWAY_NAMESPACE) --create-namespace --wait --timeout 5m
	kubectl apply -f $(GATEWAY_DIR)/envoyproxy.yaml
	kubectl apply -f $(GATEWAY_DIR)/gatewayclass.yaml
	helm upgrade --install cert-manager oci://quay.io/jetstack/charts/cert-manager \
		--version v1.21.1 -n $(CERT_MANAGER_NS) --create-namespace --set crds.enabled=true --wait --timeout 5m
	kubectl apply -f $(GATEWAY_DIR)/cert-manager-ca.yaml
	kubectl -n $(CERT_MANAGER_NS) wait --for=condition=Ready certificate/aiops-ca --timeout=300s
	kubectl -n $(GATEWAY_NAMESPACE) wait --for=condition=Ready certificate/aiops-wildcard --timeout=300s
	kubectl apply -f $(GATEWAY_DIR)/gateway.yaml
	kubectl -n $(GATEWAY_NAMESPACE) wait --for=condition=Programmed gateway/aiops --timeout=300s
	kubectl create namespace $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -
	@# The ext-authz backend: the API on the Mac, reached through a
	@# selector-less Service whose EndpointSlice carries the host IP as the
	@# kind node sees it (192.168.5.2 under colima). Override with
	@# HOST_IP=... when the lookup fails, see docs/local-dev.md.
	@host_ip="$(HOST_IP)"; \
	if [ -z "$$host_ip" ]; then \
		host_ip=$$(docker exec $(CLUSTER_NAME)-control-plane getent hosts host.docker.internal | awk '{print $$1}'); \
	fi; \
	if [ -z "$$host_ip" ]; then \
		echo "could not resolve host.docker.internal from the kind node; run 'make gateway-up HOST_IP=<ip of this Mac as seen from the node>'"; \
		exit 1; \
	fi; \
	echo "backend host IP: $$host_ip"; \
	sed "s/__HOST_IP__/$$host_ip/" $(GATEWAY_DIR)/backend-host-service.yaml | kubectl apply -f -
	kubectl apply -f $(GATEWAY_DIR)/sso.yaml
	@echo "Gateway 'aiops' ready -- https://<host>.127.0.0.1.nip.io/ via host ports 80/443."
	@echo "Run 'make ca-export trust-ca' to trust the local CA."

gateway-down: ## Remove the Gateway resources and both Helm releases (leaves the CA secrets in place)
	kubectl delete -f $(GATEWAY_DIR)/gateway.yaml --ignore-not-found
	@# Envoy Gateway must still be running to clean up the managed Envoy
	@# Deployment/Service it owns for this Gateway, so wait for that before
	@# removing its Helm release.
	-kubectl -n $(GATEWAY_NAMESPACE) wait --for=delete deployment \
		-l gateway.envoyproxy.io/owning-gateway-name=aiops --timeout=60s
	kubectl delete -f $(GATEWAY_DIR)/cert-manager-ca.yaml --ignore-not-found
	kubectl delete -f $(GATEWAY_DIR)/gatewayclass.yaml --ignore-not-found
	kubectl delete -f $(GATEWAY_DIR)/envoyproxy.yaml --ignore-not-found
	-helm uninstall cert-manager -n $(CERT_MANAGER_NS)
	-helm uninstall eg -n $(GATEWAY_NAMESPACE)
	@echo "Gateway removed. The CA secrets (aiops-ca, aiops-wildcard-tls) are left in place; delete them yourself for a fresh CA."

ca-export: ## Export the local CA certificate to infra/local/ca/ca.crt
	@mkdir -p $(CA_DIR)
	@set -o pipefail; kubectl -n $(GATEWAY_NAMESPACE) get secret aiops-wildcard-tls \
		-o jsonpath='{.data.ca\.crt}' | base64 -d > $(CA_CRT)
	@test -s $(CA_CRT)
	@echo "CA exported to $(CA_CRT)"

trust-ca: ## Print the macOS command to trust the local CA (does not run it)
	@echo "sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain $(CA_CRT)"

# --- Keycloak and the dev realm ----------------------------------------------

auth-up: ## Run Keycloak with the dev realm (auth-up; idempotent, re-applies the realm and restarts)
	kubectl create namespace $(AUTH_NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n $(AUTH_NAMESPACE) create configmap keycloak-realm \
		--from-file=$(AUTH_DIR)/realm-aiops.json --dry-run=client -o yaml | kubectl apply -f -
	kubectl apply -f $(AUTH_DIR)/keycloak.yaml
	kubectl apply -f $(AUTH_DIR)/gateway-client-secret.yaml
	kubectl -n $(AUTH_NAMESPACE) rollout restart deployment/keycloak
	kubectl -n $(AUTH_NAMESPACE) wait --for=condition=Available deployment/keycloak --timeout=300s
	@# The shared OIDC policy for workload routes: create-only, because the
	@# backend keeps adding instance routes to its targetRefs and an apply
	@# would reset the list to the one "sso" entry.
	@if kubectl -n $(NAMESPACE) get securitypolicy aiops-workloads-oidc >/dev/null 2>&1; then \
		echo "securitypolicy/aiops-workloads-oidc exists, keeping its targetRefs"; \
	else \
		kubectl create -f $(AUTH_DIR)/workloads-oidc-policy.yaml; \
	fi
	@echo ""
	@echo "Keycloak admin console: https://auth.127.0.0.1.nip.io/admin/master/console/ (admin/admin)"
	@echo "Realm 'aiops':          https://auth.127.0.0.1.nip.io/realms/aiops/account"
	@echo "Dev users (realm 'aiops', all platform-members unless noted):"
	@echo "  admin / admin  (platform-admins)"
	@echo "  alice / alice"
	@echo "  bob   / bob"

auth-down: ## Delete Keycloak and the dev realm (namespace 'auth', the ai-stack client secret and the shared OIDC policy)
	kubectl delete namespace $(AUTH_NAMESPACE) --ignore-not-found
	kubectl -n $(NAMESPACE) delete secret aiops-gateway-oidc --ignore-not-found
	kubectl -n $(NAMESPACE) delete securitypolicy aiops-workloads-oidc --ignore-not-found

# --- postgres ---------------------------------------------------------------

db-up: ## Start local Postgres (docker compose)
	docker compose -f $(COMPOSE_FILE) up -d --wait

db-down: ## Stop and remove local Postgres (data volume is kept; Langflow is untouched)
	docker compose -f $(COMPOSE_FILE) down

langflow-up: ## Serve Langflow behind the gateway (kind) on platform identity, at LANGFLOW_URL
	@# The break-glass superuser: generated once, never printed. Platform users never use it.
	@kubectl -n $(NAMESPACE) get secret langflow-superuser >/dev/null 2>&1 || \
		kubectl -n $(NAMESPACE) create secret generic langflow-superuser \
			--from-literal=username=aiops-admin \
			--from-literal=password=$$(openssl rand -hex 24)
	@# Langflow verifies tokens against the realm's JWKS over https only, so the pod
	@# reaches Keycloak through the gateway: the local CA goes in as a ConfigMap and
	@# the public auth host is aliased to the gateway's ClusterIP (see the manifest).
	@test -s $(CA_CRT) || { echo "$(CA_CRT) is missing: run 'make gateway-up ca-export' first"; exit 1; }
	kubectl -n $(NAMESPACE) create configmap aiops-ca --from-file=ca.crt=$(CA_CRT) --dry-run=client -o yaml | kubectl apply -f -
	@envoy_ip=$$(kubectl -n envoy-gateway-system get svc -l gateway.envoyproxy.io/owning-gateway-name=aiops \
		-o jsonpath='{.items[0].spec.clusterIP}'); \
	if [ -z "$$envoy_ip" ]; then echo "no Envoy Service for gateway aiops; run 'make gateway-up' first"; exit 1; fi; \
	echo "gateway ClusterIP: $$envoy_ip"; \
	sed "s/__GATEWAY_IP__/$$envoy_ip/" infra/local/langflow/langflow.yaml | kubectl apply -f -
	kubectl -n $(NAMESPACE) rollout status deployment/langflow --timeout=300s
	@echo "Langflow: $(LANGFLOW_URL) (signed in as the platform user; 'make frontend' embeds it)"

langflow-retire-shared-user: ## One-off after the switch to platform identity: deactivate the shared "langflow" user (keeps its flows)
	kubectl -n $(NAMESPACE) exec -i deploy/langflow -- python - < infra/local/langflow/retire-shared-user.py

LITELLM_URL ?= https://litellm.127.0.0.1.nip.io
GRAFANA_URL ?= https://grafana.127.0.0.1.nip.io
LITELLM_MASTER_KEY ?= sk-dev-litellm-master

litellm-up: ## Run the LiteLLM proxy on kind against the compose Postgres, behind the gateway at LITELLM_URL (idempotent)
	docker compose -f $(COMPOSE_FILE) exec -T postgres psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname='litellm'" | grep -q 1 || \
		docker compose -f $(COMPOSE_FILE) exec -T postgres psql -U postgres -c 'CREATE DATABASE litellm'
	kubectl create namespace litellm --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n litellm create secret generic litellm-master --from-literal=masterkey=$(LITELLM_MASTER_KEY) --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n litellm create secret generic litellm-db --from-literal=username=postgres --from-literal=password=postgres --dry-run=client -o yaml | kubectl apply -f -
	@# The salt key encrypts stored provider keys and must never change once set: create it only when absent (and never echo it).
	@kubectl -n litellm get secret litellm-env >/dev/null 2>&1 || \
		kubectl -n litellm create secret generic litellm-env \
			--from-literal=LITELLM_SALT_KEY=sk-salt-$$(openssl rand -hex 16) \
			--from-literal=STORE_MODEL_IN_DB=True --from-literal=DISABLE_ADMIN_UI=True
	@# The compose Postgres as the kind node sees the host (192.168.5.2 under colima); same lookup as gateway-up, HOST_IP overrides.
	@host_ip="$(HOST_IP)"; \
	if [ -z "$$host_ip" ]; then host_ip=$$(docker exec $(CLUSTER_NAME)-control-plane getent hosts host.docker.internal | awk '{print $$1}'); fi; \
	if [ -z "$$host_ip" ]; then echo "could not resolve host.docker.internal from the kind node; run 'make litellm-up HOST_IP=<ip>'"; exit 1; fi; \
	echo "LiteLLM database host: $$host_ip"; \
	helm upgrade --install litellm oci://ghcr.io/berriai/litellm-helm --version 1.99.0 -n litellm -f infra/local/litellm/values.yaml --set db.endpoint=$$host_ip --timeout 10m
	kubectl apply -f infra/local/litellm/gateway.yaml
	kubectl -n litellm rollout status deployment/litellm --timeout=600s
	@echo "LiteLLM: $(LITELLM_URL) (master key $(LITELLM_MASTER_KEY); 'make backend' passes both to the API)"

monitoring-up: ## Run Prometheus and Grafana on kind (kube-prometheus-stack), scrape LiteLLM, install the dashboards; Grafana at GRAFANA_URL
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
	helm repo update prometheus-community >/dev/null
	helm upgrade --install monitoring prometheus-community/kube-prometheus-stack --version 89.2.2 \
		-n monitoring --create-namespace -f infra/local/monitoring/values.yaml --timeout 15m
	kubectl apply -f infra/local/monitoring/gateway.yaml
	kubectl apply -f infra/local/monitoring/litellm-servicemonitor.yaml
	helm upgrade --install infracloud-dashboards charts/infracloud-dashboards -n monitoring --set grafana.namespace=monitoring
	kubectl -n monitoring rollout status deployment/monitoring-grafana --timeout=600s
	@echo "Grafana: $(GRAFANA_URL) (anonymous viewer, admin/admin; 'make frontend' passes NEXT_PUBLIC_GRAFANA_URL)"

monitoring-down: ## Remove Prometheus, Grafana, the dashboards and the Grafana route (the namespace is kept)
	kubectl delete -f infra/local/monitoring/gateway.yaml --ignore-not-found
	kubectl delete -f infra/local/monitoring/litellm-servicemonitor.yaml --ignore-not-found
	helm -n monitoring uninstall infracloud-dashboards --ignore-not-found
	helm -n monitoring uninstall monitoring --ignore-not-found

litellm-down: ## Remove the LiteLLM release and its route (the litellm database and the salt Secret are kept)
	kubectl delete -f infra/local/litellm/gateway.yaml --ignore-not-found
	helm -n litellm uninstall litellm --ignore-not-found

langflow-down: ## Remove the Langflow Deployment/Service/HTTPRoute/SecurityPolicy (the PVC and the superuser Secret are kept)
	kubectl -n $(NAMESPACE) delete deployment/langflow service/langflow httproute/langflow securitypolicy/langflow-oidc --ignore-not-found

# --- platform chart (charts/aiops-platform, docs/install.md) --------------------

CHART_DIR           := charts/aiops-platform
CHART_RELEASE       ?= aiops-platform
CHART_NAMESPACE     ?= aiops-platform
CHART_PARENT_DOMAIN ?= platform.127.0.0.1.nip.io
# Exactly seven characters, the tag the *-image.yml workflows publish (--short can give more).
CHART_IMAGE_TAG     ?= $(shell git rev-parse HEAD | cut -c1-7)
CHART_CA_SECRET     := aiops-platform-ca
CHART_TLS_SECRET    := $(CHART_RELEASE)-wildcard-tls

.PHONY: mcp-test-up mcp-test-down
.PHONY: chart-deps chart-lint chart-images chart-install chart-uninstall chart-smoke image-tag

# Helm 4 applies server-side by default and then owns the whole targetRefs
# list of the shared OIDC policy, so the first upgrade after the backend
# appended an instance route fails with a field conflict. The chart relies
# on the client-side three-way merge, which keeps the appended routes.
# Never answer that conflict with --force-conflicts: it resets the list and
# leaves every instance route without its login policy.
HELM_MERGE_FLAG := $(shell helm version --short 2>/dev/null | grep -q '^v4' && echo --server-side=false)

# The paths that trigger the *-image.yml workflows; keep the two lists the same.
IMAGE_PATHS := backend frontend .github/workflows/backend-image.yml .github/workflows/frontend-image.yml

image-tag: ## Print the newest image tag the workflows published from this branch (for global.imageTag)
	@git log -1 --format=%H -- $(IMAGE_PATHS) | cut -c1-7

chart-deps: ## Fetch the platform chart's dependencies (Bitnami postgresql and keycloak, LiteLLM)
	helm dependency build $(CHART_DIR)

chart-lint: ## Lint the platform chart and check its renders with the default, external and kind values
	./hack/chart-lint.sh

chart-images: ## Build the backend and frontend images from this checkout and load them into kind
	docker build -t ghcr.io/infracloudio/aiops-backend:$(CHART_IMAGE_TAG) backend
	docker build -t ghcr.io/infracloudio/aiops-frontend:$(CHART_IMAGE_TAG) frontend
	kind load docker-image --name $(CLUSTER_NAME) \
		ghcr.io/infracloudio/aiops-backend:$(CHART_IMAGE_TAG) \
		ghcr.io/infracloudio/aiops-frontend:$(CHART_IMAGE_TAG)

chart-install: chart-deps ## Install the platform chart on kind (namespace aiops-platform, parent domain platform.127.0.0.1.nip.io); run chart-images first
	@test -s $(CA_CRT) || { echo "$(CA_CRT) is missing: run 'make gateway-up ca-export' first"; exit 1; }
	kubectl create namespace $(CHART_NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n $(CHART_NAMESPACE) create secret generic $(CHART_CA_SECRET) --from-file=ca.crt=$(CA_CRT) \
		--dry-run=client -o yaml | kubectl apply -f -
	@# *.platform.127.0.0.1.nip.io resolves to 127.0.0.1, which inside a pod is
	@# the pod itself; the UI must reach Keycloak's public issuer, so alias the
	@# auth host to the gateway's Envoy Service.
	@envoy_ip=$$(kubectl -n $(GATEWAY_NAMESPACE) get svc -l gateway.envoyproxy.io/owning-gateway-name=aiops \
		-o jsonpath='{.items[0].spec.clusterIP}'); \
	test -n "$$envoy_ip" || { echo "no Envoy Service for Gateway aiops: run 'make gateway-up'"; exit 1; }; \
	echo "Envoy Service IP: $$envoy_ip"; \
	helm upgrade --install $(HELM_MERGE_FLAG) $(CHART_RELEASE) $(CHART_DIR) -n $(CHART_NAMESPACE) \
		-f $(CHART_DIR)/test/values-kind.yaml \
		--set global.parentDomain=$(CHART_PARENT_DOMAIN) \
		--set global.imageTag=$(CHART_IMAGE_TAG) \
		--set global.caSecret=$(CHART_CA_SECRET) \
		--set gateway.tls.secretName=$(CHART_TLS_SECRET) \
		--set-json 'frontend.hostAliases=[{"ip":"'"$$envoy_ip"'","hostnames":["auth.$(CHART_PARENT_DOMAIN)"]}]' \
		--set-json 'langflow.hostAliases=[{"ip":"'"$$envoy_ip"'","hostnames":["auth.$(CHART_PARENT_DOMAIN)"]}]' \
		--timeout 15m
	kubectl -n $(GATEWAY_NAMESPACE) wait --for=condition=Ready certificate/$(CHART_RELEASE)-wildcard --timeout=180s
	@# The dev Gateway terminates *.127.0.0.1.nip.io only (one label); add the
	@# platform wildcard certificate to its https listener, once. A later
	@# 'make gateway-up' re-applies infra/local/gateway/gateway.yaml and drops
	@# this entry again; re-run 'make chart-install' to restore it.
	@if ! kubectl -n $(GATEWAY_NAMESPACE) get gateway aiops \
		-o jsonpath='{.spec.listeners[?(@.name=="https")].tls.certificateRefs[*].name}' | grep -qw $(CHART_TLS_SECRET); then \
		kubectl -n $(GATEWAY_NAMESPACE) patch gateway aiops --type json \
			-p '[{"op":"add","path":"/spec/listeners/1/tls/certificateRefs/-","value":{"kind":"Secret","name":"$(CHART_TLS_SECRET)"}}]'; \
	fi
	kubectl -n $(CHART_NAMESPACE) rollout status statefulset/aiops-postgresql --timeout=600s
	kubectl -n $(CHART_NAMESPACE) rollout status statefulset/aiops-keycloak --timeout=900s
	kubectl -n $(CHART_NAMESPACE) rollout status deployment/aiops-litellm --timeout=600s
	kubectl -n $(CHART_NAMESPACE) rollout status deployment/$(CHART_RELEASE)-backend --timeout=600s
	kubectl -n $(CHART_NAMESPACE) rollout status deployment/$(CHART_RELEASE)-frontend --timeout=600s
	@echo ""
	@echo "UI:   https://ui.$(CHART_PARENT_DOMAIN)/   (dev users admin/admin, alice/alice, bob/bob)"
	@echo "API:  https://api.$(CHART_PARENT_DOMAIN)/health"
	@echo "Auth: https://auth.$(CHART_PARENT_DOMAIN)/realms/aiops"
	@echo "The browser must trust $(CA_CRT) (make trust-ca)."

chart-uninstall: ## Remove the platform chart from kind: the release, the namespace with its data, and the gateway certificate
	-helm -n $(CHART_NAMESPACE) uninstall $(CHART_RELEASE)
	@refs=$$(kubectl -n $(GATEWAY_NAMESPACE) get gateway aiops -o json 2>/dev/null \
		| jq -c '[.spec.listeners[] | select(.name=="https") | .tls.certificateRefs[] | select(.name != "$(CHART_TLS_SECRET)")]'); \
	if [ -n "$$refs" ]; then \
		kubectl -n $(GATEWAY_NAMESPACE) patch gateway aiops --type json \
			-p '[{"op":"replace","path":"/spec/listeners/1/tls/certificateRefs","value":'"$$refs"'}]'; \
	fi
	kubectl -n $(GATEWAY_NAMESPACE) delete secret $(CHART_TLS_SECRET) --ignore-not-found
	kubectl delete namespace $(CHART_NAMESPACE) --ignore-not-found

chart-smoke: ## Install the platform chart on kind and check the API, the realm and the login page through the gateway (ARGS="--skip-install" reuses an install)
	CHART_RELEASE=$(CHART_RELEASE) CHART_NAMESPACE=$(CHART_NAMESPACE) PARENT_DOMAIN=$(CHART_PARENT_DOMAIN) CA_CERT=$(CA_CRT) \
		./hack/chart-smoke.sh $(ARGS)

# --- LoadBalancer support (optional, needs sudo -- not run by this Makefile) -

lb: ## Print the cloud-provider-kind command to enable LoadBalancer IPs (requires sudo, run it yourself)
	@echo "cloud-provider-kind is optional: without it, Services of type LoadBalancer"
	@echo "stay Pending and the backend falls back to the ClusterIP for the endpoint."
	@echo "Install:  brew install cloud-provider-kind"
	@echo ""
	@echo "Run it yourself in another terminal (this Makefile will not run sudo):"
	@echo ""
	@echo "  DOCKER_HOST=unix://$${HOME}/.colima/default/docker.sock sudo cloud-provider-kind"
	@echo ""

# --- backend / frontend ------------------------------------------------------

registry-export: ## Export the model registry of the local Postgres to backend/raw_data/models.yaml (review the diff, then commit)
	cd backend && \
		DATABASE_URL=postgresql://localhost:5432 \
		DATABASE_NAME=postgres \
		DATABASE_USER=postgres \
		DATABASE_PASSWORD=postgres \
		uv run python scripts/registry_export.py
	@git -C . diff --stat backend/raw_data/models.yaml

db-migrate: ## Apply the Alembic migrations to the local Postgres
	cd backend && \
		DATABASE_URL=postgresql://localhost:5432 \
		DATABASE_NAME=postgres \
		DATABASE_USER=postgres \
		DATABASE_PASSWORD=postgres \
		uv run alembic upgrade head

# The backend trusts the local CA (gateway hosts) and the public roots
# (Hugging Face, OpenAI, chart repositories) through one bundle built from
# certifi's cacert.pem plus infra/local/ca/ca.crt.
CA_BUNDLE := $(CA_DIR)/bundle.crt

$(CA_BUNDLE): $(CA_CRT)
	cd backend && cat "$$(uv run python -c 'import certifi; print(certifi.where())')" ../$(CA_CRT) > ../$(CA_BUNDLE)

backend: $(CA_BUNDLE) ## Run the backend API with uv (needs helm on PATH and a kubeconfig)
	cd backend && \
		DATABASE_URL=postgresql://localhost:5432 \
		DATABASE_NAME=postgres \
		DATABASE_USER=postgres \
		DATABASE_PASSWORD=postgres \
		AIOPS_NAMESPACE=$(NAMESPACE) \
		AUTH_MODE=$(AUTH_MODE) \
		OIDC_ISSUER=$(OIDC_ISSUER) \
		AIOPS_PARENT_DOMAIN=127.0.0.1.nip.io \
		AIOPS_GATEWAY_NAME=aiops \
		AIOPS_GATEWAY_NAMESPACE=envoy-gateway-system \
		AIOPS_CHARTS_DIR=$(PWD)/charts \
		LITELLM_URL=$(LITELLM_URL) \
		LITELLM_MASTER_KEY=$(LITELLM_MASTER_KEY) \
		LANGFLOW_API_URL=$(LANGFLOW_URL) \
		LITELLM_CLUSTER_URL=http://litellm.litellm.svc:4000 \
		AIOPS_BACKEND_CLUSTER_URL=http://aiops-backend.ai-stack.svc:8000 \
		AIOPS_MCP_ALLOW_INSECURE_HOSTS=$(MCP_TEST_HOST) \
		SSL_CERT_FILE=$(PWD)/$(CA_BUNDLE) \
		REQUESTS_CA_BUNDLE=$(PWD)/$(CA_BUNDLE) \
		uv run uvicorn app:app --reload --port 8000

frontend: ## Run the frontend dev server with pnpm (Keycloak login; AUTH_MODE=disabled turns it off)
	cd frontend && pnpm install --frozen-lockfile && \
		NEXT_PUBLIC_LANGFLOW_URL=$(LANGFLOW_URL) \
		NEXT_PUBLIC_GRAFANA_URL=$(GRAFANA_URL) \
		AUTH_MODE=$(AUTH_MODE) \
		NEXT_PUBLIC_AUTH_MODE=$(AUTH_MODE) \
		AUTH_SECRET=$(AUTH_SECRET) \
		AUTH_URL=$(FRONTEND_URL) \
		AUTH_KEYCLOAK_ISSUER=$(KEYCLOAK_ISSUER) \
		AUTH_KEYCLOAK_ID=aiops-ui \
		NODE_EXTRA_CA_CERTS=$(PWD)/$(CA_CRT) \
		pnpm dev

# --- smoke test ---------------------------------------------------------------

e2e-smoke: ## Run the end-to-end smoke test against a running backend (ARGS="--skip-notebook --skip-ollama" skips those parts)
	BACKEND_URL=$(BACKEND_URL) AUTH_MODE=$(AUTH_MODE) OIDC_ISSUER=$(OIDC_ISSUER) CA_CERT=$(CA_CRT) \
		AUTOMATION_CLIENT_ID=$(AUTOMATION_CLIENT_ID) AUTOMATION_CLIENT_SECRET=$(AUTOMATION_CLIENT_SECRET) \
		./hack/e2e-smoke.sh $(ARGS)

# --- UI end-to-end tests (Playwright, see docs/testing.md) -------------------

# --- MCP test server ---------------------------------------------------------------

MCP_TEST_HOST := mcp-test.mcp-test.svc.cluster.local

mcp-test-up: ## Deploy the local MCP test server (echo, whoami; needs a bearer) for the cluster e2e tier
	kubectl apply -f infra/local/mcp/test-server.yaml
	kubectl -n mcp-test rollout status deployment/mcp-test --timeout=300s
	@echo "MCP test server: http://$(MCP_TEST_HOST):8000/mcp (any bearer; 'make backend' allows this host)"

mcp-test-down: ## Remove the local MCP test server
	-kubectl delete -f infra/local/mcp/test-server.yaml --ignore-not-found

ui-e2e: ## Run the fast UI e2e tier; starts a TEST_MODE backend on :8001 and a built frontend on :3001
	cd frontend && E2E_START_SERVERS=1 pnpm e2e $(ARGS)

ui-e2e-cluster: ## Run the cluster UI e2e tier against the running stack (FRONTEND_URL, BACKEND_URL)
	cd frontend && E2E_BASE_URL=$(FRONTEND_URL) E2E_BACKEND_URL=$(BACKEND_URL) pnpm e2e:cluster $(ARGS)

# --- dev convenience ------------------------------------------------------------

dev: ## Print the order to bring the whole stack up locally
	@echo "Local dev stack -- run in this order (separate terminals where noted):"
	@echo ""
	@echo "  1. make prereqs         # confirm tools are installed"
	@echo "  2. colima start         # if not already running (4 CPU / 8 GiB)"
	@echo "  3. make kind-up         # kind cluster + notebook-controller + namespace"
	@echo "  4. make gateway-up      # Envoy Gateway, cert-manager, local CA, sso host"
	@echo "  5. make ca-export       # writes infra/local/ca/ca.crt (then: make trust-ca)"
	@echo "  6. make auth-up         # Keycloak with the dev realm (alice/bob/admin)"
	@echo "  7. make db-up           # postgres on :5432"
	@echo "  8. make langflow-up     # optional, Langflow behind the gateway"
	@echo "  9. make litellm-up      # optional, LiteLLM provider layer (chat targets, embeddings, rerank, metrics)"
	@echo " 10. make monitoring-up   # optional, Prometheus + Grafana with the LiteLLM dashboard"
	@echo " 11. make backend         # (separate terminal) FastAPI on :8000 with OIDC"
	@echo " 12. make frontend        # (separate terminal) Next.js on :3000, Keycloak login"
	@echo " 13. make e2e-smoke       # API smoke with an automation token"
	@echo " 14. make ui-e2e          # Playwright fast tier (no cluster, AUTH_MODE=disabled)"
	@echo " 15. make ui-e2e-cluster  # Playwright cluster tier, logged in as alice"
	@echo ""
	@echo "Tear down:"
	@echo "  make db-down monitoring-down litellm-down langflow-down auth-down gateway-down kind-down"

.DEFAULT_GOAL := help
