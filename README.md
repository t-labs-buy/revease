# Refract V1

> Record once. Refract into everything. Capture a workflow → AI generates a polished video → edit → AI regenerates. Single-user, runs locally.

See [V1-CORE-PLAN.md](V1-CORE-PLAN.md) for scope and [PROGRESS.md](PROGRESS.md) for status.

## Layout
```
apps/web         Next.js (App Router, TS, Tailwind) — dashboard + editor
apps/api         FastAPI (3.12) — SQLite, local media store, no auth
apps/workers     Celery + Redis — AI pipeline (media/ml/llm/render)
apps/extension   MV3 capture extension (P1)
packages/workflow-graph  IR JSON Schema + Python & TS validators (single source of truth)
```

## Quick start
```bash
cp .env.example .env      # fill provider keys when you reach P2/P3
make install              # npm workspaces + uv envs
make dev                  # redis + api :8000 + worker + web :3000
```
Health check: `curl -f http://localhost:8000/healthz`

## Tests
```bash
make test                 # workflow-graph (TS + Py) + api
```

## Prereqs
Node 20+, Python 3.12 (via `uv`), Docker (Redis), ffmpeg. NVIDIA CUDA 12.x for GPU Whisper (P2).
