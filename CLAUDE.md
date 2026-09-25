# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Refract / RevEase: capture a software workflow (screen recorder, MV3 extension, upload, or AI-driven "Auto Record") → an AI pipeline turns it into a **Workflow Graph** → the graph drives a generated studio video (TTS voiceover, click-zooms, captions) and a step-by-step doc → the user edits → **only changed segments regenerate**.

Naming is split: the code, env prefix (`REFRACT_`), packages and volumes say **Refract**; the product/UI, git repo and Docker images say **RevEase**. Both are the same thing — don't "fix" one to the other.

Planning docs: [V1-CORE-PLAN.md](V1-CORE-PLAN.md) (scope), [PROGRESS.md](PROGRESS.md) (what's built + verification notes), [V2-DEVELOPMENT-PLAN.md](V2-DEVELOPMENT-PLAN.md) (gap analysis). The last two lag the code — several things marked ❌/missing in V2-DEVELOPMENT-PLAN (sharing, docs export, skills, KB, brand packages) now exist. Trust the code, update the docs when you ship.

## Commands

```bash
make install          # npm workspaces + per-app uv envs (+ Whisper extra) + Kokoro TTS model (~350MB)
make dev              # redis (podman or docker compose, auto-detected) + api :8000 + celery worker + web :3000
make doctor           # check node / uv / container engine / ffmpeg / .env
make redis|api|worker|web   # each piece in its own terminal (`make worker` consumes both queues)
make test             # workflow-graph (Py + TS) + api + workers
make lint             # ruff (api, workers) + eslint (workspaces)
make typecheck        # mypy app (non-blocking) + tsc --noEmit per workspace
make fmt              # ruff format
make clean            # rm -rf data/  (SQLite + all media — destructive)
```

Single tests:
```bash
cd apps/api     && uv run pytest tests/test_auth.py::test_login_returns_token -q
cd apps/workers && uv run pytest tests/test_timeline.py -q -k drift
cd packages/workflow-graph/python && uv run --with pytest --with jsonschema pytest -q
npm run test --workspace @refract/workflow-graph      # node --test over src/index.test.ts
```

Docker deploy: `python shift.py --tag v1` builds/pushes `tlabsdoc/revease:{api,worker,web}-<tag>`; `TAG=v1 docker compose -f docker-compose.prod.yml up -d` runs it. See [DOCKER.md](DOCKER.md). The web image bakes `NEXT_PUBLIC_API_BASE` at build time, so LAN access needs a web rebuild with `--api-base`.

`make purge-legacy` / `purge-legacy-force` deletes pre-auth ownerless rows — destructive, dry-run first.

## Architecture

```
apps/web        Next.js 15 App Router, TS, Tailwind (no shadcn; hand-rolled ui.tsx)
apps/api        FastAPI 3.12 — SQLite (SQLAlchemy 2.0 sync), local media store, JWT auth
apps/workers    Celery + Redis — media/whisper/segment/extract + TTS + FFmpeg render
apps/extension  MV3 — telemetry capture + Auto Record (CDP-driven tab)
packages/workflow-graph  JSON Schema (draft 2020-12) + Python & TS validators
```

**Dependency direction is one-way: workers import the API package (`app.models`, `app.storage`, `app.editspec`), never the reverse.** The API enqueues work by task *name* through [apps/api/app/queue.py](apps/api/app/queue.py) so it never imports worker code. `apps/workers/pyproject.toml` declares `refract-api` as an editable path dep — that's what makes it work.

### The spine

1. **Capture** → `CaptureSession` + `Event` rows + media assets. All four sources (`recorder | extension | upload | auto`) emit the *same* session/event shape, so the pipeline is source-agnostic — except the `auto` branch, which is special-cased in `run_pipeline`.
2. **Understanding** ([apps/workers/worker/pipeline/run.py](apps/workers/worker/pipeline/run.py)): stages `media → whisper → merge → extract`, each with a `Job` row keyed `(session_id, stage, version)` so re-runs are idempotent. `version = max(existing graph version for project) + 1`. media/whisper degrade gracefully (log + continue); **extract does not** — no graph means an unusable project, so it errors loudly.
3. **Workflow Graph** — the IR and single source of truth. Schema lives in [packages/workflow-graph/schema/workflow-graph.schema.json](packages/workflow-graph/schema/workflow-graph.schema.json); the TS types in `src/index.ts` are mirrored **by hand** — change both. Every graph is validated before persisting. Never renumber `steps[].id` between stages.
4. **Edit spec** ([apps/api/app/editspec.py](apps/api/app/editspec.py)) — the editable layer built lazily from a graph (script tokens, filler indices, zooms, scenes, captions). **Shared by API and worker** so effective narration is computed identically on both sides; if you change one side's derivation you've introduced drift.
5. **Render** ([apps/workers/worker/pipeline/render.py](apps/workers/worker/pipeline/render.py)) — per-segment clips cached by content hash, concatenated. Render happens **only on export**; preview is client-side.

### Two invariants that everything else rests on

- **`build_timeline` is pure and must never drift.** [apps/workers/worker/pipeline/timeline.py](apps/workers/worker/pipeline/timeline.py) builds the output clock *entirely* from per-step TTS durations, so `sum(seg.out_duration_ms) == total` by construction. Original click timestamps are only ever mapped *into* those slots as source windows. No I/O in this module; [tests/test_timeline.py](apps/workers/tests/test_timeline.py) is the exhaustive edge-case suite and is the gate on any change here.
- **Regenerate re-renders only what changed.** Per-clip content hash + TTS cache keyed `(text_hash, voice_id, speed, provider)`. A render returns stats proving it (`rendered N / reused M`). Anything that perturbs a hash for an unrelated edit silently kills the feature — the render tests assert the reuse counts.

### Long-running work: queues, duplicates, progress

- Two Celery queues ([apps/api/app/tasking.py](apps/api/app/tasking.py)): `media` (pipeline, render, auto-edit) and `default` (documents, snapshots, TTS previews). Production runs one worker per queue (`-Q media -c 1`, `-Q default -c 3`) so a long encode never blocks quick jobs.
- Redis `visibility_timeout` is raised to 12h (`REFRACT_CELERY_VISIBILITY_TIMEOUT_S`). At Celery's 1h default a long normalize was redelivered to a second slot and two ffmpegs wrote the same file.
- A running stage heartbeats `Job.updated_at` every ~20s ([worker/pipeline/progress.py](apps/workers/worker/pipeline/progress.py)). `run_pipeline` drops a redelivered copy (same `pipeline_token`) while a stage is live, defers a genuinely new request until the live run ends, and takes over a stale one. The API refuses `reprocess` with 409 while live.
- ffmpeg normalize is bounded: `-r 30` constant frame rate (browser WebM reports 1000 fps), `-threads`, a timeout, and a write to `source.part.mp4` renamed on success.
- Jobs, documents and renders carry `progress` (0..1) + `message`; `GET /sessions/{id}/status` adds an overall progress and ETA ([apps/api/app/progress.py](apps/api/app/progress.py)); `GET /activity` feeds the header indicator.

### Providers all degrade to offline determinism

Every external dependency sits behind an adapter that works with no key and no GPU, which is why the whole suite runs offline:

| | Preferred | Fallbacks |
|---|---|---|
| LLM (step labels, narration, rewrite, Auto Record agent) | Anthropic SDK, `REFRACT_ANTHROPIC_MODEL` | OpenRouter → deterministic labeler |
| STT | faster-whisper (`whisper` extra) | empty transcript |
| TTS | Kokoro (local, keyless, default) | Piper → OpenAI → silent clip of estimated duration |
| Tracing | Langfuse + OTel Anthropic auto-instrumentation | no-op when unconfigured |

`init_tracing()` must run **before** any Anthropic client is constructed — it's called in the API lifespan and in the Celery `worker_process_init` signal.

### Auth & ownership

JWT bearer, stateless HS256. Only four models carry `user_id`: `Project`, `Skill`, `KbArticle`, `BrandPackage`. Everything else hangs off a Project, and [apps/api/app/ownership.py](apps/api/app/ownership.py) is the single place an id becomes a row you may touch.

- **A row you don't own returns 404, never 403** — a 403 would confirm the id exists.
- New routes go through `owned_*` helpers + `CurrentUser`. Public by design: `/auth/*`, `/healthz`, `/voices*`, `GET /media/{key}` (a `<video src>` can't send a header; keys embed UUIDs), `GET /shares/{token}`.
- Web: [apps/web/lib/http.ts](apps/web/lib/http.ts) is the *only* transport — it attaches the token and bounces to `/login` on 401, and deliberately **does not throw on non-2xx** (callers branch on `r.ok`/`r.status`). `AuthGate` in the root layout makes every route private unless whitelisted, so new pages are private by default.
- Extension: only `src/api.js` knows about auth (reads `accessToken` from `chrome.storage.local`).

### Persistence

SQLite by default (WAL + `busy_timeout`), Postgres via `REFRACT_DATABASE_URL=postgresql+psycopg://…`; the whole test suite passes on both (`REFRACT_TEST_DATABASE_URL`). **No Alembic.** `init_db()` runs `create_all` then additively `ADD COLUMN`s anything new through SQLAlchemy's inspector ([apps/api/app/db.py](apps/api/app/db.py)) — so schema changes must be additive (new nullable columns / new tables). `python -m app.dbcopy` copies SQLite into Postgres.

Media goes through [apps/api/app/storage.py](apps/api/app/storage.py): `local` (a dir) or `s3` (MinIO / AWS). **The contract every media call follows:** read with `store.fetch(key)` (S3 downloads into a per-process cache), write at `store.local_path(key)` then `store.commit(key)` / `commit_tree(prefix)`, or `store.write(key, bytes)`. Scratch dirs (render segment cache, TTS cache) use `local_path` and never commit. A new write that browsers or another process must see **needs a commit**, or it only exists on one machine. Browsers always get `/media/{key}`; on S3 that 307s to a presigned URL whose origin is swapped to `REFRACT_S3_PUBLIC_URL` (SigV4 signs host + path, so an nginx `/s3/` route with `Host: <minio>:9000` validates). Large captures upload as resumable multipart ([apps/api/app/routers/uploads.py](apps/api/app/routers/uploads.py), [apps/web/lib/upload.ts](apps/web/lib/upload.ts)) straight to the store. The media stage also writes a 540p `proxy` asset in the same ffmpeg pass; the editor previews that, renders read the full source. [apps/api/app/retention.py](apps/api/app/retention.py) runs hourly via Celery beat.

Config: one `Settings` (pydantic-settings, `REFRACT_` prefix) that loads the **repo-root** `.env` regardless of CWD, since api and worker both run from `apps/*`. Always read config via `get_settings()`.

## Conventions

- Module docstrings carry the *why* — the non-obvious tradeoff, the bug that motivated a constant, what breaks if you change it. Match that when adding modules; it's the main form of documentation here.
- Both Python apps: ruff, line-length 100, `from __future__ import annotations`.
- Tests isolate onto a temp SQLite + media dir in `conftest.py` **before any app import**; workers' conftest also strips API keys and forces `REFRACT_DISABLE_WHISPER` / `TTS_PROVIDER=silent` for determinism. Keep new tests offline-deterministic.
- Segmentation, timeline, diff and editspec are pure functions over plain data — keep them that way so they stay exhaustively testable.
- Web imports use the `@/*` alias; API calls go through `lib/api.ts` (which uses `lib/http.ts`), never bare `fetch`.
- macOS: the Makefile prepends `/opt/homebrew/opt/ffmpeg-full/bin` to `PATH` — Homebrew's plain ffmpeg lacks `drawtext`, which captions need.
