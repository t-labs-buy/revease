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
infra/docker     Dockerfiles (api / worker / web); shift.py + docker-compose.prod.yml deploy the stack
```

## Running on a new machine

### 1. System prerequisites
Install these once. All are keyless/free.

| Tool | Version | Notes |
|------|---------|-------|
| Node.js | 20+ | web app + workspace scripts |
| Python | 3.12 | managed per-app by `uv` |
| uv | latest | Python env/dependency manager |
| Docker | any | runs Redis for background jobs |
| ffmpeg | 4+ | media probing, trim, render |
| git | any | clone |

**Ubuntu/Debian**
```bash
# Node 20 (via nvm)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash && . ~/.nvm/nvm.sh && nvm install 20
# uv (installs its own Python 3.12)
curl -LsSf https://astral.sh/uv/install.sh | sh
# ffmpeg + docker
sudo apt-get update && sudo apt-get install -y ffmpeg docker.io
```

**macOS (Homebrew)**
```bash
brew install node@20 uv ffmpeg
brew install --cask docker    # then launch Docker Desktop once
```

### 2. Clone & configure
```bash
git clone https://github.com/t-labs-buy/revease.git
cd revease
cp .env.example .env          # defaults work out of the box; add AI keys only if you want LLM/cloud TTS
```

### 3. Install dependencies
```bash
make install                  # npm workspaces + per-app uv envs (+ Whisper) + downloads the Kokoro TTS model (~350MB)
```
This runs `npm install`, `uv sync` for `apps/api` and `apps/workers`, and `make kokoro-model`. First run pulls the neural TTS model, so give it a few minutes.

### 4. Run everything
```bash
make dev                      # starts Redis (Docker) + api :8000 + Celery worker + web :3000
```
Open **http://localhost:3000**. Health check: `curl -f http://localhost:8000/healthz`.

Prefer separate terminals? `make redis`, `make api`, `make worker`, `make web` run each piece individually.

### 5. (Optional) Capture extension
Load `apps/extension` as an unpacked MV3 extension: Chrome → `chrome://extensions` → enable Developer mode → **Load unpacked** → select the folder.

### AI / TTS keys (optional)
The app runs fully local with keyless defaults (Kokoro TTS, local Whisper). To enable Claude step-labeling/narration set `REFRACT_ANTHROPIC_API_KEY` in `.env`. TTS provider is selectable via `REFRACT_TTS_PROVIDER` (`kokoro` | `piper` | `openai`). See `.env.example` for all `REFRACT_`-prefixed options.

### GPU (optional)
For fast transcription on an NVIDIA GPU (CUDA 12.x), set `REFRACT_WHISPER_DEVICE=cuda` and `REFRACT_WHISPER_COMPUTE=float16` in `.env`.

## Docker deployment

Run the whole stack as containers — no Node/Python/uv toolchain needed on the target box, only Docker. See [DOCKER.md](DOCKER.md) for the full guide.

### Registry & images
All three services publish to one Docker Hub repo, distinguished by a tag prefix:

| Service | Image | Port |
|---------|-------|------|
| Web (Next.js) | `tlabsdoc/revease:web-<tag>` | 3000 |
| API (FastAPI) | `tlabsdoc/revease:api-<tag>` | 8000 |
| Worker (Celery + FFmpeg) | `tlabsdoc/revease:worker-<tag>` | — |
| Redis (broker) | `redis:7-alpine` | 6379 |

API + worker share one named volume (`refract-data` — SQLite + media + TTS model), so they must run on the **same host**.

### Build & push to Docker Hub
From a machine with the source + Docker:
```bash
docker login                      # as the tlabsdoc user (once)
python shift.py --tag v1          # build + push api-/worker-/web-v1 (and *-latest)
```
`shift.py` wraps `docker build` + `docker push tlabsdoc/revease:<service>-<tag>`. Useful flags:
```bash
python shift.py --service web --tag v1                 # one service only
python shift.py --tag v1 --api-base http://10.0.0.5:8000   # bake browser→API URL into web
python shift.py --tag v1 --no-whisper                  # lighter worker image
python shift.py --tag v1 --platform linux/amd64,linux/arm64   # multi-arch (buildx)
python shift.py --tag v1 --no-push                     # build only
```

### Run on another system
Copy `docker-compose.prod.yml` + `.env.docker.example` to the target host (Docker only) — images are pulled from Docker Hub:
```bash
cp .env.docker.example .env       # add REFRACT_ANTHROPIC_API_KEY etc. (optional — degrades gracefully)
TAG=v1 docker compose -f docker-compose.prod.yml up -d
```
Open **http://localhost:3000**.

To build from source on the host instead of pulling: `docker compose -f docker-compose.prod.yml build`.

**Accessing from another machine (LAN/remote):** the browser calls the API directly, and that URL is baked into the web image at build time. Rebuild web with the host's address, set CORS to match, and redeploy:
```bash
python shift.py --service web --tag v1 --api-base http://<host-ip>:8000
# in .env on the host:  CORS_ORIGINS=http://<host-ip>:3000
TAG=v1 docker compose -f docker-compose.prod.yml up -d
```

**Notes:** the worker downloads the ~350MB Kokoro TTS model into the volume on first start (`REFRACT_FETCH_KOKORO=0` to skip → Piper fallback). Data persists in the `refract-data` volume; `docker compose down -v` wipes it.

## Tests
```bash
make test                 # workflow-graph (TS + Py) + api + workers
make typecheck            # mypy + per-workspace tsc
make lint                 # ruff + eslint
```

## Troubleshooting
- **`redis` connection refused** — ensure Docker is running; `make redis` starts it. On Linux you may need `sudo usermod -aG docker $USER` (re-login) or run Docker commands with `sudo`.
- **`ffmpeg: command not found`** — install ffmpeg (see prereqs); render/trim need it.
- **Port already in use** — something else is on `:3000`/`:8000`/`:6379`; stop it or change the port in the Makefile / `.env`.
- **Kokoro model missing** — re-run `make kokoro-model` (idempotent, resumes partial downloads).
