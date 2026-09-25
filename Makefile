.DEFAULT_GOAL := help
SHELL := /bin/bash

# --- paths ---
API_DIR := apps/api
WORKERS_DIR := apps/workers
WEB_DIR := apps/web
GRAPH_PY := packages/workflow-graph/python

# Homebrew's plain ffmpeg is a slim build without drawtext (no libfreetype), which
# the renderer needs for captions. Prefer the keg-only ffmpeg-full when present;
# harmless no-op on Linux/Docker where the system ffmpeg already has drawtext.
# ~/.local/bin is where the uv installer puts itself, so a fresh `make install`
# can bootstrap uv and use it in the same run without a shell restart.
export PATH := /opt/homebrew/opt/ffmpeg-full/bin:$(HOME)/.local/bin:$(PATH)

# --- container engine ---
# Redis is the only container we need locally. Podman is a drop-in here: its
# `podman compose` delegates to docker-compose/podman-compose, so the same
# compose file works for both. Auto-picks podman when installed; override with
#   make redis CONTAINER_ENGINE=docker
CONTAINER_ENGINE ?= $(shell command -v podman >/dev/null 2>&1 && echo podman || echo docker)
COMPOSE := $(CONTAINER_ENGINE) compose

.PHONY: infra-up infra-down retention retention-dry db-copy storage-migrate help doctor install uv env redis redis-stop dev api worker web test test-py test-js lint typecheck fmt purge-legacy purge-legacy-force clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

doctor: ## Check the local toolchain (node, uv, container engine, ffmpeg)
	@ok() { printf "  \033[32m✓\033[0m %-10s %s\n" "$$1" "$$2"; }; miss() { printf "  \033[31m✗\033[0m %-10s %s\n" "$$1" "$$2"; }; \
	command -v node >/dev/null && ok node "$$(node --version)" || miss node "install Node 20+ (nvm)"; \
	command -v uv >/dev/null && ok uv "$$(uv --version)" || miss uv "run 'make uv'"; \
	command -v $(CONTAINER_ENGINE) >/dev/null && ok $(CONTAINER_ENGINE) "$$($(CONTAINER_ENGINE) --version | head -1)" || miss $(CONTAINER_ENGINE) "install podman (brew install podman) or docker"; \
	$(COMPOSE) version >/dev/null 2>&1 && ok compose "$$($(COMPOSE) version 2>/dev/null | head -1)" || miss compose "podman needs docker-compose or podman-compose on PATH"; \
	command -v ffmpeg >/dev/null && ok ffmpeg "$$(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f1-3)" || miss ffmpeg "brew install ffmpeg (media + render stages degrade without it)"; \
	[ -f .env ] && ok .env "present" || miss .env "run 'make env' (copies .env.example)"

install: uv env ## Install all deps (npm workspaces + uv envs; workers include Whisper) + Kokoro voice model
	npm install
	cd $(API_DIR) && uv sync
	cd $(WORKERS_DIR) && uv sync --extra whisper
	$(MAKE) kokoro-model
	@command -v ffmpeg >/dev/null || echo "WARNING: ffmpeg not found — media and render stages will degrade. brew install ffmpeg"

uv: ## Install uv (Python package manager) into ~/.local/bin if missing
	@command -v uv >/dev/null 2>&1 || { echo "Installing uv…"; curl -LsSf https://astral.sh/uv/install.sh | sh; }

env: ## Create .env from .env.example if missing
	@[ -f .env ] || { cp .env.example .env; echo "Created .env from .env.example — edit it to add API keys"; }

kokoro-model: ## Download the Kokoro TTS model into data/kokoro (~350MB, once)
	@mkdir -p data/kokoro
	@set -e; base=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0; \
	fetch() { curl -fL --retry 5 --retry-all-errors --speed-limit 10240 --speed-time 60 -C - "$$base/$$1" -o "data/kokoro/$$1.part" && mv "data/kokoro/$$1.part" "data/kokoro/$$1"; }; \
	[ -f data/kokoro/kokoro-v1.0.onnx ] || fetch kokoro-v1.0.onnx; \
	[ -f data/kokoro/voices-v1.0.bin ] || fetch voices-v1.0.bin; \
	echo "Kokoro model ready in data/kokoro"

redis: ## Start Redis (podman or docker compose; starts the podman VM if needed)
	@if [ "$(CONTAINER_ENGINE)" = podman ]; then \
		podman machine inspect --format '{{.State}}' 2>/dev/null | grep -q running || podman machine start; \
	fi
	$(COMPOSE) up -d redis

infra-up: ## Start optional MinIO (:9000, console :9001) + Postgres (:5432) for s3/postgres mode
	$(COMPOSE) up -d minio postgres

infra-down: ## Stop MinIO + Postgres
	$(COMPOSE) stop minio postgres

retention-dry: ## Show what the retention sweep would delete
	cd $(API_DIR) && uv run python -m app.retention --dry-run

retention: ## Run the retention sweep now (also runs hourly via Celery beat)
	cd $(API_DIR) && uv run python -m app.retention

db-copy: ## Copy SQLite into Postgres: make db-copy TARGET=postgresql+psycopg://user:pass@host/db
	cd $(API_DIR) && uv run python -m app.dbcopy --source sqlite:///$(CURDIR)/data/refract.sqlite3 --target "$(TARGET)"

storage-migrate: ## Copy data/media into the S3 bucket (needs REFRACT_STORAGE_BACKEND=s3 settings)
	cd $(API_DIR) && uv run python -m app.storage_migrate --from $(CURDIR)/data/media

redis-stop: ## Stop Redis
	$(COMPOSE) down

api: ## Run the FastAPI dev server
	cd $(API_DIR) && uv run uvicorn app.main:app --reload --port 8000

worker: ## Run a Celery worker on both queues (media + default)
	cd $(WORKERS_DIR) && uv run celery -A worker.celery_app worker --loglevel=info -Q media,default

web: ## Run the Next.js dev server
	cd $(WEB_DIR) && npm run dev

dev: env redis ## Run web + api + worker locally (Ctrl-C stops all)
	@echo "Starting api :8000, worker, web :3000 — Ctrl-C to stop"
	@trap 'kill 0' EXIT INT TERM; \
	( cd $(API_DIR) && uv run uvicorn app.main:app --reload --port 8000 ) & \
	( cd $(WORKERS_DIR) && uv run celery -A worker.celery_app worker --loglevel=info -Q media -c 1 -n media@%h ) & \
	( cd $(WORKERS_DIR) && uv run celery -A worker.celery_app worker --loglevel=info -Q default -c 3 -n default@%h -B -s ../../data/celerybeat-schedule ) & \
	( cd $(WEB_DIR) && npm run dev ) & \
	wait

test: test-py test-js ## Run all tests

test-py: ## Run Python tests (workflow-graph + api + workers)
	cd $(GRAPH_PY) && uv run --with pytest --with jsonschema pytest -q
	cd $(API_DIR) && uv run pytest -q
	cd $(WORKERS_DIR) && uv run pytest -q

test-js: ## Run JS/TS tests (workflow-graph)
	npm run test --workspace @refract/workflow-graph

lint: ## Lint all apps
	cd $(API_DIR) && uv run ruff check .
	cd $(WORKERS_DIR) && uv run ruff check .
	npm run lint --workspaces --if-present

typecheck: ## Typecheck all apps
	cd $(API_DIR) && uv run mypy app || true
	npm run typecheck --workspaces --if-present

fmt: ## Format Python
	cd $(API_DIR) && uv run ruff format .
	cd $(WORKERS_DIR) && uv run ruff format .

purge-legacy: ## Show pre-auth ownerless rows (projects/skills/articles/packages) — dry run
	cd $(API_DIR) && uv run python -m app.purge

purge-legacy-force: ## DELETE those ownerless rows and their media. Back up data/ first!
	cd $(API_DIR) && uv run python -m app.purge --yes

clean: ## Remove local data (SQLite + media)
	rm -rf data
