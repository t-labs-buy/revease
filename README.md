# RevEase

> Record once. Refract into everything. Capture a software workflow → AI turns it into a polished, narrated video **and** a step-by-step guide with annotated screenshots → edit either → only what changed regenerates. Multi-user: every account gets its own private space.

The product is **RevEase**; the code, packages and `REFRACT_` settings say **Refract** — same thing. See [CLAUDE.md](CLAUDE.md) for architecture and conventions, [PROGRESS.md](PROGRESS.md) for what's built, [DOCKER.md](DOCKER.md) for container deployment and [infra/ivolve/README.md](infra/ivolve/README.md) for the live deployment.

## What it does

| | |
|---|---|
| **Capture** | Screen recorder, file upload (MP4/MOV/WebM, up to 50 GB, resumable), MV3 extension, or AI-driven "Auto Record" |
| **Understand** | Converts the recording, transcribes speech (Whisper), detects steps, labels them with Claude → a **Workflow Graph** |
| **Video** | Studio editor: script, voiceover (Kokoro TTS), click-zooms, captions, crops, brand kit; renders only changed scenes |
| **Documentation** | AI-written guide (overview, prerequisites, steps with tips) + a snapshot per step grabbed at the click and highlighted; inline editing; export **Word / PDF / Markdown**; share links |
| **Visibility** | Live progress with ETA for every long job (processing, document writing, rendering) and a header activity indicator |
| **Downloads** | Original recording or processed MP4, straight from storage |

## Layout
```
apps/web         Next.js 15 (App Router, TS, Tailwind) — dashboard, editor, document editor
apps/api         FastAPI (Python 3.12) — SQLite or Postgres, local disk or S3 media, JWT auth
apps/workers     Celery + Redis — media / whisper / LLM / snapshots / render
apps/extension   MV3 capture extension
packages/workflow-graph  Workflow Graph JSON Schema + Python & TS validators
infra/docker     Dockerfiles (api / worker / web)
infra/ivolve     The live deployment (compose, edge nginx, build + backup scripts)
```

## Architecture at a glance

```
browser ──/────────▶ web (Next.js)
        ──/api/────▶ api (FastAPI) ──▶ Postgres | SQLite
        ──/s3/─────▶ object storage (MinIO / S3) ◀── presigned uploads & downloads
                         ▲
Redis ──▶ worker (queue "media": convert, transcribe, render; 1 at a time)
      └─▶ worker-light (queue "default": documents, snapshots, voice previews; + hourly retention)
```

- **Two queues** so a long encode never blocks quick jobs. Long tasks heartbeat; a redelivered duplicate is dropped, never run twice.
- **Storage is pluggable** (`REFRACT_STORAGE_BACKEND=local|s3`). With S3 the API and workers share nothing but the bucket and the database, so workers can run on other machines. Browsers upload and download directly against storage.
- **Database is pluggable** (`REFRACT_DATABASE_URL`): SQLite by default, Postgres when several workers write at once.
- Everything external degrades gracefully: no API key → deterministic labelling and writing; no GPU → CPU Whisper; no ffmpeg → no media stages.

## Running locally

### 1. Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Node.js | 20+ | web app + workspace scripts |
| uv | latest | Python env manager (installs Python 3.12; `make install` bootstraps it) |
| Podman or Docker | any | runs Redis (and optionally MinIO + Postgres) |
| ffmpeg | 5.1+ | conversion, snapshots, render (`-fps_mode`; Homebrew's `ffmpeg-full` adds captions) |
| git | any | |

**macOS**
```bash
brew install node@20 uv ffmpeg podman docker-compose
podman machine init && podman machine start      # or Docker Desktop
```
**Ubuntu/Debian**
```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash && . ~/.nvm/nvm.sh && nvm install 20
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo apt-get update && sudo apt-get install -y ffmpeg podman podman-compose   # or docker.io
```
`make doctor` reports anything missing. The Makefile uses Podman when installed, else Docker (`CONTAINER_ENGINE=docker` to force).

### 2. Configure and install
```bash
git clone https://github.com/t-labs-buy/revease.git && cd revease
make install      # creates .env from .env.example, npm + uv envs (+Whisper), Kokoro TTS model (~350 MB)
```
Defaults work with no keys. Add `REFRACT_ANTHROPIC_API_KEY` for Claude-written labels, narration and documentation.

### 3. Run
```bash
make dev          # Redis + api :8000 + media worker + light worker (with beat) + web :3000
```
Open **http://localhost:3000**. Individual pieces: `make redis`, `make api`, `make worker` (both queues), `make web`.

### Optional: run the way production scales (MinIO + Postgres)
```bash
make infra-up                                   # MinIO :9000 (console :9001) + Postgres :5432
# POSTGRES_PORT=5442 MINIO_PORT=9100 make infra-up   if those ports are taken
```
Then in `.env`:
```bash
REFRACT_STORAGE_BACKEND=s3
REFRACT_S3_ENDPOINT_URL=http://localhost:9000
REFRACT_S3_PUBLIC_URL=http://localhost:9000
REFRACT_S3_ACCESS_KEY=revease
REFRACT_S3_SECRET_KEY=revease-dev-secret
REFRACT_DATABASE_URL=postgresql+psycopg://revease:revease@localhost:5432/revease
```
Existing local data moves over with `make db-copy TARGET=<postgres url>` and `make storage-migrate`.

## Configuration

All settings are `REFRACT_`-prefixed and documented in [.env.example](.env.example). The ones that matter most:

| Area | Setting | Default | Notes |
|---|---|---|---|
| AI | `REFRACT_ANTHROPIC_API_KEY` | empty | Claude for labels, narration, documentation; OpenRouter fallback via `REFRACT_OPENROUTER_API_KEY` |
| Storage | `REFRACT_STORAGE_BACKEND` | `local` | `s3` + `REFRACT_S3_*` for MinIO / AWS S3 |
| Storage | `REFRACT_S3_PUBLIC_URL` | empty | what browsers use in presigned URLs (e.g. `/s3` behind the edge proxy) |
| Database | `REFRACT_DATABASE_URL` | SQLite in `data/` | `postgresql+psycopg://…` for Postgres |
| Uploads | `REFRACT_UPLOAD_PART_MB` | 16 | resumable upload part size |
| Processing | `REFRACT_MEDIA_THREADS` / `_NORMALIZE_FPS` | 4 / 30 | caps per ffmpeg job |
| Processing | `REFRACT_CELERY_VISIBILITY_TIMEOUT_S` | 43200 | must exceed the longest job |
| Retention | `REFRACT_RETENTION_*` | 7 d originals, 2 d audio, 7 d old renders, 30 d TTS, 24 h uploads | `0` disables a rule |
| Speech | `REFRACT_WHISPER_MODEL` / `_DEVICE` | `small` / `cpu` | `cuda` + `float16` on an NVIDIA GPU |
| Voice | `REFRACT_TTS_PROVIDER` | `kokoro` | `piper` / `openai` / `silent` |

## Operations

```bash
make retention-dry        # what the hourly cleanup would delete
make retention            # run it now
make db-copy TARGET=…     # copy SQLite into Postgres (refuses a non-empty target)
make storage-migrate      # copy data/media into the S3 bucket (re-runnable)
```

What retention deletes, and only after the grace period: the browser's original WebM once a processed MP4 exists, the transcription WAV, renders superseded by a newer one, cached voice clips, and abandoned uploads. Users can download the original from the Download menu until then; afterwards they get the processed MP4.

## Deployment

- **Containers**: [DOCKER.md](DOCKER.md) — `python shift.py --repo <registry>/revease --tag vN` builds and pushes `api-`, `worker-` and `web-` images (Docker or Podman; `--platform linux/amd64` from an Apple-silicon Mac, though the web image must be built natively). `docker-compose.prod.yml` runs the stack with a worker per queue.
- **Live (ivolve cloud)**: [infra/ivolve/README.md](infra/ivolve/README.md) — images at `reg.ivolve.cloud/ivolve/revease`, MinIO + Postgres, single-origin edge proxy.

## Tests
```bash
make test                 # workflow-graph (TS + Py) + api + workers — offline, deterministic
make typecheck            # mypy + tsc per workspace
make lint                 # ruff (+ eslint where configured)
REFRACT_TEST_DATABASE_URL=postgresql+psycopg://… make test-py   # the same suites on Postgres
```
The S3 backend is tested against moto's in-memory S3; worker tests that need ffmpeg skip without it.

## Troubleshooting
- **Redis connection refused**: `make redis` (starts the Podman machine if needed).
- **`Unrecognized option 'vsync'`**: an old worker build on ffmpeg 7+; current code uses `-fps_mode`.
- **MinIO image pull denied**: Docker Hub no longer serves MinIO community images; compose uses `quay.io/minio/minio`.
- **Port already in use**: change `POSTGRES_PORT` / `MINIO_PORT`, or run the web dev server with `npx next dev -p 3001` and add that origin to `REFRACT_CORS_ORIGINS`.
- **Unstyled web page after `npm run build`**: the build overwrote the dev server's `.next`; stop dev, `rm -rf apps/web/.next`, start again.
- **Kokoro model missing**: `make kokoro-model` (resumable, fails loudly on a bad download).
- **A recording seems stuck**: the header activity menu shows its stage; "No update for a few minutes" means the media worker is busy with another long job.
