# Engine Room — local dev runner.
#
# Two ways to see everything running:
#   make demo      all-in-Docker: db + backend + frontend + a looping bot (one command)
#   make dev       host hot-reload stack (db in Docker; backend+frontend reload)
#                  then, in another terminal:  make bot   # start a game to watch
#
# Ports: backend :8001, frontend :5174, Postgres :5433. See CLAUDE.md.
SHELL := /bin/bash
COMPOSE := docker compose
# Pace the house bot so demo games are watchable move-by-move. Scoped to the
# server-running recipes only (NOT `make test` — it would sleep through games).
# Production leaves ER_HOUSE_MOVE_DELAY_SECONDS at its default 0 = instant.
HOUSE_DELAY := ER_HOUSE_MOVE_DELAY_SECONDS=0.5

.DEFAULT_GOAL := help

.PHONY: help install db migrate backend frontend dev mint bot demo up down test

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install: ## Install backend (uv) + frontend (npm) deps — once per clone
	cd server && uv sync
	cd frontend && npm install

db: ## Start Postgres (Docker) and wait until it's healthy
	$(COMPOSE) up -d db
	@echo "waiting for Postgres…"; \
	until [ "$$($(COMPOSE) ps -q db | xargs docker inspect -f '{{.State.Health.Status}}' 2>/dev/null)" = "healthy" ]; do sleep 1; done; \
	echo "Postgres ready on :5433"

migrate: db ## Apply DB migrations (creates tables + seeds the house bot)
	cd server && uv run alembic upgrade head

backend: ## Run the backend with hot reload (:8001)
	cd server && $(HOUSE_DELAY) uv run uvicorn engine_room.app:app --reload --port 8001

frontend: ## Run the SvelteKit dev server with hot reload (:5174)
	cd frontend && npm run dev

dev: migrate ## Hot-reload stack: db + backend + frontend (Ctrl-C stops all)
	@echo "backend → http://localhost:8001   frontend → http://localhost:5174"
	@echo "in another terminal:  make bot   (starts a game to watch)"
	@trap 'kill 0' EXIT INT TERM; \
	( cd server && $(HOUSE_DELAY) uv run uvicorn engine_room.app:app --reload --port 8001 ) & \
	( cd frontend && npm run dev ) & \
	wait

mint: ## Mint a fresh local bot API key (prints it)
	cd server && uv run python -m engine_room.devtools.mint_bot

bot: ## Start random-mover games vs the house and print the watch URL (needs a running stack)
	cd server && uv run python -m engine_room.devtools.demo_bot --loop

demo: ## One command: db + backend + frontend + a looping bot, all in Docker
	@echo "Building & starting the whole platform + a demo bot…"
	@echo "When it's up, open http://localhost:5174 and use the game URL from the demo-bot logs."
	$(COMPOSE) --profile demo up --build

up: ## Whole platform in Docker (no bot)
	$(COMPOSE) --profile app up --build

down: ## Stop and remove all local containers
	$(COMPOSE) --profile demo down

test: ## Fast gate: ruff + unit tests + svelte-check
	cd server && uv run ruff check . && uv run pytest tests/unit -q
	cd frontend && npm run check

e2e: migrate ## Playwright smoke: dashboard → watch → replay (starts backend+frontend itself)
	cd frontend && npm ci && npx playwright install chromium && \
		ER_AMBIENT_MOVE_DELAY_SECONDS=0.15 npm run e2e
