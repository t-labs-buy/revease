.DEFAULT_GOAL := help
SHELL := /bin/bash

# --- paths ---
API_DIR := apps/api
WORKERS_DIR := apps/workers
WEB_DIR := apps/web
GRAPH_PY := packages/workflow-graph/python

.PHONY: help install redis dev api worker web test test-py test-js lint typecheck fmt clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install all deps (npm workspaces + uv envs; workers include Whisper) + Kokoro voice model
	npm install
	cd $(API_DIR) && uv sync
	cd $(WORKERS_DIR) && uv sync --extra whisper
	$(MAKE) kokoro-model

kokoro-model: ## Download the Kokoro TTS model into data/kokoro (~350MB, once)
	@mkdir -p data/kokoro
	@base=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0; \
	[ -f data/kokoro/kokoro-v1.0.onnx ] || curl -fsSL -C - $$base/kokoro-v1.0.onnx -o data/kokoro/kokoro-v1.0.onnx; \
	[ -f data/kokoro/voices-v1.0.bin ] || curl -fsSL -C - $$base/voices-v1.0.bin -o data/kokoro/voices-v1.0.bin; \
	echo "Kokoro model ready in data/kokoro"

redis: ## Start Redis (Docker)
	docker compose up -d redis

api: ## Run the FastAPI dev server
	cd $(API_DIR) && uv run uvicorn app.main:app --reload --port 8000

worker: ## Run the Celery worker
	cd $(WORKERS_DIR) && uv run celery -A worker.celery_app worker --loglevel=info

web: ## Run the Next.js dev server
	cd $(WEB_DIR) && npm run dev

dev: redis ## Run web + api + worker locally (Ctrl-C stops all)
	@echo "Starting api :8000, worker, web :3000 — Ctrl-C to stop"
	@trap 'kill 0' EXIT INT TERM; \
	( cd $(API_DIR) && uv run uvicorn app.main:app --reload --port 8000 ) & \
	( cd $(WORKERS_DIR) && uv run celery -A worker.celery_app worker --loglevel=info ) & \
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

clean: ## Remove local data (SQLite + media)
	rm -rf data
