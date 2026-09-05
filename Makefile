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

langflow-up: ## Serve Langflow behind the gateway (kind), OIDC-protected, at LANGFLOW_URL
	kubectl apply -f infra/local/langflow/langflow.yaml
	kubectl -n $(NAMESPACE) wait --for=condition=Available deployment/langflow --timeout=300s
	@echo "Langflow: $(LANGFLOW_URL) (the frontend embeds it when NEXT_PUBLIC_LANGFLOW_URL is set; 'make frontend' sets it)"

langflow-down: ## Remove the Langflow Deployment/Service/HTTPRoute/SecurityPolicy (the PVC is kept)
	kubectl -n $(NAMESPACE) delete deployment/langflow service/langflow httproute/langflow securitypolicy/langflow-oidc --ignore-not-found

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

db-migrate: ## Apply the Alembic migrations to the local Postgres
	cd backend && \
		DATABASE_URL=postgresql://localhost:5432 \
		DATABASE_NAME=postgres \
		DATABASE_USER=postgres \
		DATABASE_PASSWORD=postgres \
		uv run alembic upgrade head

backend: ## Run the backend API with uv (needs helm on PATH and a kubeconfig)
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
		SSL_CERT_FILE=$(PWD)/infra/local/ca/ca.crt \
		REQUESTS_CA_BUNDLE=$(PWD)/infra/local/ca/ca.crt \
		uv run uvicorn app:app --reload --port 8000

frontend: ## Run the frontend dev server with pnpm (Keycloak login; AUTH_MODE=disabled turns it off)
	cd frontend && pnpm install --frozen-lockfile && \
		NEXT_PUBLIC_LANGFLOW_URL=$(LANGFLOW_URL) \
		AUTH_MODE=$(AUTH_MODE) \
		NEXT_PUBLIC_AUTH_MODE=$(AUTH_MODE) \
		AUTH_SECRET=$(AUTH_SECRET) \
		AUTH_URL=$(FRONTEND_URL) \
		AUTH_KEYCLOAK_ISSUER=$(KEYCLOAK_ISSUER) \
		AUTH_KEYCLOAK_ID=aiops-ui \
		NODE_EXTRA_CA_CERTS=$(PWD)/$(CA_CRT) \
		pnpm dev

# --- smoke test ---------------------------------------------------------------

e2e-smoke: ## Run the end-to-end smoke test against a running backend (pass ARGS="--skip-notebook" to skip the notebook part)
	BACKEND_URL=$(BACKEND_URL) AUTH_MODE=$(AUTH_MODE) OIDC_ISSUER=$(OIDC_ISSUER) CA_CERT=$(CA_CRT) \
		AUTOMATION_CLIENT_ID=$(AUTOMATION_CLIENT_ID) AUTOMATION_CLIENT_SECRET=$(AUTOMATION_CLIENT_SECRET) \
		./hack/e2e-smoke.sh $(ARGS)

# --- UI end-to-end tests (Playwright, see docs/testing.md) -------------------

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
	@echo "  9. make backend         # (separate terminal) FastAPI on :8000 with OIDC"
	@echo " 10. make frontend        # (separate terminal) Next.js on :3000, Keycloak login"
	@echo " 11. make e2e-smoke       # API smoke with an automation token"
	@echo " 12. make ui-e2e          # Playwright fast tier (no cluster, AUTH_MODE=disabled)"
	@echo " 13. make ui-e2e-cluster  # Playwright cluster tier, logged in as alice"
	@echo ""
	@echo "Tear down:"
	@echo "  make db-down langflow-down auth-down gateway-down kind-down"

.DEFAULT_GOAL := help
