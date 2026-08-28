.DEFAULT_GOAL := help

COMPOSE ?= docker compose
COMPOSE_ATLAS ?= $(COMPOSE) -p recql-mongo-atlas
COMPOSE_COMMUNITY ?= $(COMPOSE) -p recql-mongo-community -f docker-compose.community.yml
PYTHON ?= $(shell command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)
PYTEST ?= $(PYTHON) -m pytest
# Host port 27018 by default (compose maps → container 27017).
MONGO_PORT ?= 27018
DSN ?= mongodb://127.0.0.1:$(MONGO_PORT)/recql?directConnection=true
DSN_COMMUNITY ?= mongodb://recql:recql@127.0.0.1:$(MONGO_PORT)/recql?directConnection=true&authSource=admin
RECQL_CORE_PATH ?= ../recql-python-core
RECQL_PLAYGROUND_PATH ?= ../recql-playground

export MONGO_PORT
export RECQL_CORE_PATH
export RECQL_PLAYGROUND_PATH

.PHONY: help up down reset logs build-conformance test test-unit test-conformance
.PHONY: up-community down-community reset-community test-conformance-docker-community
.PHONY: test-conformance-docker test-conformance-community

help: ## Show targets
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_-]+:.*## / {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf '\nDocker (recommended): make test-conformance-docker\n'
	@printf 'Community variant:    make test-conformance-docker-community\n'
	@printf 'Default host port is $(MONGO_PORT) (set MONGO_PORT=… to override).\n'
	@printf 'Atlas DSN:     $(DSN)\n'
	@printf 'Community DSN: $(DSN_COMMUNITY)\n'

up: ## Start Atlas Local MongoDB and wait for healthy
	$(COMPOSE_ATLAS) up -d mongodb
	@echo "waiting for healthy… (DSN=$(DSN))"
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do \
	  st=$$($(COMPOSE_ATLAS) ps mongodb --format '{{.Health}}' 2>/dev/null || true); \
	  if [ "$$st" = "healthy" ]; then \
	    echo "mongodb healthy"; \
	    sleep 3; \
	    exit 0; \
	  fi; \
	  if $(COMPOSE_ATLAS) ps -a mongodb --format '{{.Status}}' 2>/dev/null | grep -qi exited; then \
	    echo "mongodb exited — see: make logs"; exit 1; \
	  fi; \
	  sleep 2; \
	done; \
	echo "timed out waiting for healthy"; exit 1

up-community: ## Start Community Server + mongot and wait for healthy
	chmod +x docker/community/docker-compose-entrypoint.sh
	$(COMPOSE_COMMUNITY) up -d mongodb mongot
	@echo "waiting for mongodb + mongot healthy… (DSN=$(DSN_COMMUNITY))"
	@for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45; do \
	  md=$$($(COMPOSE_COMMUNITY) ps mongodb --format '{{.Health}}' 2>/dev/null || true); \
	  mt=$$($(COMPOSE_COMMUNITY) ps mongot --format '{{.Health}}' 2>/dev/null || true); \
	  if [ "$$md" = "healthy" ] && [ "$$mt" = "healthy" ]; then \
	    echo "community stack healthy"; \
	    $(COMPOSE_COMMUNITY) exec -T mongodb mongosh -u admin -p adminPassword --authenticationDatabase admin --quiet --eval 'for (let i = 0; i < 60; i++) { const h = db.hello(); if (h.isWritablePrimary || h.primary) quit(0); sleep(500); } quit(1);' && exit 0; \
	  fi; \
	  sleep 2; \
	done; \
	echo "timed out waiting for community stack"; exit 1

down: ## Stop Atlas Local containers (keep volumes)
	$(COMPOSE_ATLAS) down

down-community: ## Stop Community stack (keep volumes)
	$(COMPOSE_COMMUNITY) down

reset: ## Wipe Atlas Local volume and stop
	$(COMPOSE_ATLAS) down -v

reset-community: ## Wipe Community volumes and stop
	$(COMPOSE_COMMUNITY) down -v

logs: ## Tail Atlas Local MongoDB logs
	$(COMPOSE_ATLAS) logs -f mongodb

build-conformance: ## Build the conformance runner image
	$(COMPOSE_ATLAS) --profile conformance build conformance

test-unit: ## Backend-specific unit tests (no DB)
	@command -v $(PYTHON) >/dev/null || { echo "No $(PYTHON) on PATH"; exit 127; }
	$(PYTEST) tests/unit -q

test-conformance: ## Shared suite on the host (needs make up + local installs)
	@command -v $(PYTHON) >/dev/null || { echo "No $(PYTHON) on PATH — use: make test-conformance-docker"; exit 127; }
	RECQL_MONGODB_DSN=$(DSN) $(PYTEST) tests/ -q

test-conformance-community: ## Shared suite on host against Community stack
	@command -v $(PYTHON) >/dev/null || { echo "No $(PYTHON) on PATH — use: make test-conformance-docker-community"; exit 127; }
	RECQL_MONGODB_DSN='$(DSN_COMMUNITY)' $(PYTEST) tests/ -q

test-conformance-docker: ## Atlas Local + run suite inside Docker (recommended / CI default)
	@$(MAKE) down-community
	@$(MAKE) reset
	@$(MAKE) up
	$(COMPOSE_ATLAS) --profile conformance run --rm --build conformance

test-conformance-docker-community: ## Community Server + mongot + run suite inside Docker
	@$(MAKE) down
	@$(MAKE) reset-community
	@$(MAKE) up-community
	$(COMPOSE_COMMUNITY) --profile conformance run --rm --build conformance

test: test-conformance-docker ## Default: full docker conformance (Atlas Local)
