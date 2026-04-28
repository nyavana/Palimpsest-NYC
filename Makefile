# Palimpsest NYC — developer tasks
#
# Convention: every Python subproject under apps/ owns its own .venv.
# Prefer `uv` for speed; fall back to stdlib `venv + pip` if uv is absent.

SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose
PY := python3
UV := $(shell command -v uv 2> /dev/null)

API_DIR := apps/api
WORKER_DIR := apps/worker
WEB_DIR := apps/web

API_VENV := $(API_DIR)/.venv
WORKER_VENV := $(WORKER_DIR)/.venv

# ─────────────────────────────── help ───────────────────────────────

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make \033[36m<target>\033[0m\n\nTargets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ─────────────────────────────── setup ──────────────────────────────

.PHONY: setup
setup: setup-api setup-worker setup-web ## Create venvs and install all deps

.PHONY: setup-api
setup-api: ## Create apps/api/.venv and install dependencies
	@echo "→ Setting up $(API_DIR)/.venv"
ifeq ($(UV),)
	@cd $(API_DIR) && $(PY) -m venv .venv && . .venv/bin/activate && pip install --upgrade pip && pip install -e '.[dev]'
else
	@cd $(API_DIR) && uv venv && uv sync --all-extras
endif

.PHONY: setup-worker
setup-worker: ## Create apps/worker/.venv and install dependencies
	@echo "→ Setting up $(WORKER_DIR)/.venv"
ifeq ($(UV),)
	@cd $(WORKER_DIR) && $(PY) -m venv .venv && . .venv/bin/activate && pip install --upgrade pip && pip install -e '.[dev]'
else
	@cd $(WORKER_DIR) && uv venv && uv sync --all-extras
endif

.PHONY: setup-web
setup-web: ## Install web dependencies
	@echo "→ Installing $(WEB_DIR) deps"
	@cd $(WEB_DIR) && npm install

# ────────────────────────────── docker ──────────────────────────────

.PHONY: up
up: ## Start the full stack in the background
	$(COMPOSE) up -d --build

.PHONY: dev
dev: ## Start the full stack attached (live logs)
	$(COMPOSE) up --build

.PHONY: down
down: ## Stop and remove containers
	$(COMPOSE) down

.PHONY: nuke
nuke: ## Stop containers AND remove volumes (destructive)
	$(COMPOSE) down -v

.PHONY: logs
logs: ## Tail all container logs
	$(COMPOSE) logs -f --tail 100

.PHONY: ps
ps: ## Show container status
	$(COMPOSE) ps

.PHONY: api-shell
api-shell: ## Open a shell inside the api container
	$(COMPOSE) exec api bash

.PHONY: db-shell
db-shell: ## Open psql inside the postgres container
	$(COMPOSE) exec postgres psql -U palimpsest -d palimpsest

# ────────────────────────────── quality ─────────────────────────────

.PHONY: fmt
fmt: fmt-py fmt-web ## Format all code

.PHONY: fmt-py
fmt-py: ## Format Python with ruff
	@cd $(API_DIR) && . .venv/bin/activate && ruff format app tests 2>/dev/null || true
	@cd $(WORKER_DIR) && . .venv/bin/activate && ruff format worker 2>/dev/null || true

.PHONY: fmt-web
fmt-web: ## Format web with prettier
	@cd $(WEB_DIR) && npm run format 2>/dev/null || true

.PHONY: lint
lint: lint-py lint-web ## Lint all code

.PHONY: lint-py
lint-py: ## Lint Python with ruff
	@cd $(API_DIR) && . .venv/bin/activate && ruff check app tests 2>/dev/null || true
	@cd $(WORKER_DIR) && . .venv/bin/activate && ruff check worker 2>/dev/null || true

.PHONY: lint-web
lint-web: ## Lint web with eslint
	@cd $(WEB_DIR) && npm run lint 2>/dev/null || true

.PHONY: test
test: test-py ## Run all tests

.PHONY: test-py
test-py: ## Run Python tests with pytest
	@cd $(API_DIR) && . .venv/bin/activate && pytest -q

# ────────────────────────────── openspec ────────────────────────────

.PHONY: spec-list
spec-list: ## List openspec changes
	@openspec list

.PHONY: spec-validate
spec-validate: ## Validate all openspec changes
	@openspec validate initial-palimpsest-scaffold --strict

.PHONY: spec-show
spec-show: ## Show active change summary
	@openspec show initial-palimpsest-scaffold
