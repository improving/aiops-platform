SHELL := /bin/bash

.PHONY: help prereqs kind-up kind-down db-up db-down lb backend frontend e2e-smoke ui-e2e ui-e2e-cluster dev

# --- Variables ----------------------------------------------------------

CLUSTER_NAME       ?= aiops
NAMESPACE          ?= ai-stack
BACKEND_URL        ?= http://localhost:8000
FRONTEND_URL       ?= http://localhost:3000
KIND_CONFIG        := infra/local/kind-config.yaml
COMPOSE_FILE       := infra/local/docker-compose.yml
LANGFLOW_URL       ?= http://localhost:7860
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

# --- postgres ---------------------------------------------------------------

db-up: ## Start local Postgres (docker compose)
	docker compose -f $(COMPOSE_FILE) up -d --wait

db-down: ## Stop and remove local Postgres (and Langflow if running)
	docker compose -f $(COMPOSE_FILE) --profile langflow down

langflow-up: ## Start Langflow for the Develop page (docker compose profile)
	docker compose -f $(COMPOSE_FILE) --profile langflow up -d --wait langflow
	@echo "Langflow: $(LANGFLOW_URL) (the frontend embeds it when NEXT_PUBLIC_LANGFLOW_URL is set; 'make frontend' sets it)"

langflow-down: ## Stop and remove Langflow
	docker compose -f $(COMPOSE_FILE) --profile langflow rm -sf langflow

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

backend: ## Run the backend API with uv (needs helm on PATH and a kubeconfig)
	cd backend && \
		DATABASE_URL=postgresql://localhost:5432 \
		DATABASE_NAME=postgres \
		DATABASE_USER=postgres \
		DATABASE_PASSWORD=postgres \
		AIOPS_NAMESPACE=$(NAMESPACE) \
		uv run uvicorn app:app --reload --port 8000

frontend: ## Run the frontend dev server with pnpm (embeds Langflow from LANGFLOW_URL)
	cd frontend && pnpm install --frozen-lockfile && \
		NEXT_PUBLIC_LANGFLOW_URL=$(LANGFLOW_URL) pnpm dev

# --- smoke test ---------------------------------------------------------------

e2e-smoke: ## Run the end-to-end smoke test against a running backend (pass ARGS="--skip-notebook" to skip the notebook part)
	BACKEND_URL=$(BACKEND_URL) ./hack/e2e-smoke.sh $(ARGS)

# --- UI end-to-end tests (Playwright, see docs/testing.md) -------------------

ui-e2e: ## Run the fast UI e2e tier; starts a TEST_MODE backend on :8001 and a built frontend on :3001
	cd frontend && E2E_START_SERVERS=1 pnpm e2e $(ARGS)

ui-e2e-cluster: ## Run the cluster UI e2e tier against the running stack (FRONTEND_URL, BACKEND_URL)
	cd frontend && E2E_BASE_URL=$(FRONTEND_URL) E2E_BACKEND_URL=$(BACKEND_URL) pnpm e2e:cluster $(ARGS)

# --- dev convenience ------------------------------------------------------------

dev: ## Print the order to bring the whole stack up locally
	@echo "Local dev stack -- run in this order (separate terminals where noted):"
	@echo ""
	@echo "  1. make prereqs        # confirm tools are installed"
	@echo "  2. colima start        # if not already running"
	@echo "  3. make kind-up        # kind cluster + notebook-controller + namespace"
	@echo "  4. make db-up          # postgres on :5432"
	@echo "  5. make backend        # (separate terminal) FastAPI on :8000"
	@echo "  6. make frontend       # (separate terminal, optional) Next.js on :3000"
	@echo "  7. make e2e-smoke      # exercises the backend API against the cluster"
	@echo "  8. make ui-e2e         # Playwright fast tier (no cluster needed)"
	@echo "  9. make ui-e2e-cluster # Playwright cluster tier against :3000 and :8000"
	@echo ""
	@echo "Optional, for Services of type LoadBalancer to get a real IP:"
	@echo "  make lb                # prints the sudo cloud-provider-kind command"
	@echo ""
	@echo "Tear down:"
	@echo "  make db-down"
	@echo "  make kind-down"

.DEFAULT_GOAL := help
