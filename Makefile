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

# ─────────────────────────────── osrm ───────────────────────────────

OSRM_BBOX := -74.000,40.795,-73.955,40.825
OSRM_EXTRACT := infra/osrm/extract.osm.pbf
BBBIKE_URL := https://extract.bbbike.org/?sw_lng=-74.000&sw_lat=40.795&ne_lng=-73.955&ne_lat=40.825&format=osm.pbf&city=MorningsideHeights-UWS

.PHONY: extract
extract: ## Print the BBBike URL and curl command to download the OSM extract
	@echo ""
	@echo "=== OSM Extract Download ==="
	@echo ""
	@echo "1. Open this URL in your browser to request the extract from BBBike:"
	@echo "   $(BBBIKE_URL)"
	@echo ""
	@echo "   BBBike will email you a download link (~3-8 MB .osm.pbf)."
	@echo ""
	@echo "2. Once you have the download URL from the email, run:"
	@echo "   curl -L <DOWNLOAD_URL> -o $(OSRM_EXTRACT)"
	@echo ""
	@echo "   Or (Geofabrik + osmium alternative — requires osmium-tool installed):"
	@echo "   curl -L https://download.geofabrik.de/north-america/us/new-york-latest.osm.pbf -o /tmp/ny.osm.pbf"
	@echo "   osmium extract --bbox $(OSRM_BBOX) /tmp/ny.osm.pbf -o $(OSRM_EXTRACT)"
	@echo ""
	@echo "3. Then run:  make up"
	@echo "   osrm-prepare will preprocess the extract (~2 min on first run)."
	@echo ""

# ─────────────────────────────── eval ───────────────────────────────

.PHONY: eval-setup eval-deps eval-shell

eval-setup: docs/eval/.venv/.installed

docs/eval/.venv/.installed: docs/eval/requirements.txt
	python3 -m venv docs/eval/.venv
	docs/eval/.venv/bin/pip install --upgrade pip
	docs/eval/.venv/bin/pip install -r docs/eval/requirements.txt
	touch $@

eval-deps:
	docs/eval/.venv/bin/pip install -r docs/eval/requirements.txt

eval-shell:
	@echo "Run: source docs/eval/.venv/bin/activate"

# ─────────────────────────────── prod ───────────────────────────────
#
# `up-prod` etc. wrap docker-compose.prod.yml. PALIMPSEST_TAG is the
# image tag used across the three palimpsest images and is also read
# from .env by docker compose. Override on the CLI:
#   make build-prod PALIMPSEST_TAG=0.2.0

PALIMPSEST_TAG ?= 0.1.0
PROD_COMPOSE := $(COMPOSE) -f docker-compose.prod.yml
PROD_IMAGES := ghcr.io/nyavana/palimpsest-api ghcr.io/nyavana/palimpsest-web ghcr.io/nyavana/palimpsest-postgres

.PHONY: build-prod
build-prod: ## Build prod images locally, tagged with PALIMPSEST_TAG
	PALIMPSEST_TAG=$(PALIMPSEST_TAG) $(PROD_COMPOSE) build

.PHONY: push-prod
push-prod: ## Push prod images to ghcr.io (requires `docker login ghcr.io`)
	@for img in $(PROD_IMAGES); do \
		echo "→ pushing $$img:$(PALIMPSEST_TAG)"; \
		docker push $$img:$(PALIMPSEST_TAG) || exit 1; \
	done

.PHONY: up-prod
up-prod: ## Start the prod stack in the background
	PALIMPSEST_TAG=$(PALIMPSEST_TAG) $(PROD_COMPOSE) up -d

.PHONY: down-prod
down-prod: ## Stop the prod stack (volumes preserved)
	$(PROD_COMPOSE) down

# ─────────────────────────────── harden ─────────────────────────────
#
# Host-side hardening. Run on the prod host after the cutover.
# `harden` is idempotent and safe to re-run; `harden-cutover` is a
# one-shot dev→prod migration and must not be re-run blindly.

.PHONY: harden
harden: harden-perms harden-firewall ## Run all idempotent hardening (perms + firewall)

.PHONY: harden-perms
harden-perms: ## chmod 600 .env; verify mode
	@if [ ! -f .env ]; then echo "no .env present"; exit 1; fi
	@chmod 600 .env
	@echo ".env is now $$(stat -c '%a' .env)"

.PHONY: harden-firewall
harden-firewall: ## Refresh the Cloudflare-IP UFW allowlist
	@if [ ! -x /usr/local/sbin/refresh-cf-ufw ]; then \
		echo "refresh-cf-ufw not installed — run: sudo bash infra/host/install.sh"; \
		exit 1; \
	fi
	sudo /usr/local/sbin/refresh-cf-ufw
	@sudo ufw status numbered | grep -E 'cf-allowlist|22/tcp'

.PHONY: harden-cutover
harden-cutover: ## One-shot dev→prod cutover (DESTRUCTIVE — see infra/host/cutover.sh)
	@if [ ! -f infra/host/cutover.sh ]; then echo "missing infra/host/cutover.sh"; exit 1; fi
	bash infra/host/cutover.sh

.PHONY: verify-harden
verify-harden: ## Read-only checks that the hardening is in place
	@echo "== .env perms (want 600) =="
	@stat -c '%a' .env
	@echo
	@echo "== publicly-listening sockets (want only :22, :80, :443) =="
	@sudo ss -tlnp | grep LISTEN || true
	@echo
	@echo "== api container caps + readonly rootfs =="
	@sudo docker inspect palimpsest-api --format 'CapDrop={{.HostConfig.CapDrop}} ReadonlyRootfs={{.HostConfig.ReadonlyRootfs}} Memory={{.HostConfig.Memory}}' 2>&1 || true
	@echo
	@echo "== UFW cf-allowlist rule count (want >= 26: 16 v4 + 10 v6, both ports) =="
	@sudo ufw status numbered | grep -c cf-allowlist || true
	@echo
	@echo "== /api/docs response (want 404 once APP_ENV=production) =="
	@curl -sf -o /dev/null -w 'http_code=%{http_code}\n' https://palimpsest-demo.nyavana.io/api/docs || true
