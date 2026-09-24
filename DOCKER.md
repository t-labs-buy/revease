# Running Refract with Docker

Three service images live in one Docker Hub repo, distinguished by a tag prefix:

| Service | Image | Port |
|---------|-------|------|
| Web (Next.js) | `tlabsdoc/revease:web-<tag>` | 3000 |
| API (FastAPI) | `tlabsdoc/revease:api-<tag>` | 8000 |
| Worker (Celery + FFmpeg) | `tlabsdoc/revease:worker-<tag>` | — |
| Redis (broker) | `redis:7-alpine` | 6379 |

API + worker share one named volume (`refract-data`) holding the SQLite DB, media,
and the TTS model — they must run on the **same host**.

## Push images (build machine)

```bash
docker login                       # once, as the tlabsdoc user
python shift.py --tag v1           # builds + pushes api-/worker-/web-v1 (and *-latest)
```

Useful flags: `--service web|api|worker`, `--no-push` (build only),
`--api-base http://<host-ip>:8000` (bake the browser→API URL into web),
`--no-whisper` (lighter worker), `--platform linux/amd64,linux/arm64` (buildx),
`--repo <registry>/<owner>/revease` (any OCI registry, not just Docker Hub),
`--engine podman` (auto-picked when docker is absent).

### Podman on an Apple-silicon Mac → the ivolve Gitea registry

```bash
podman login reg.ivolve.cloud                         # once; Gitea registry, paths are <owner>/<image>
python3 shift.py --engine podman --platform linux/amd64 \
  --repo reg.ivolve.cloud/ivolve/revease --tag v2 --api-base /api --service api
python3 shift.py --engine podman --platform linux/amd64 \
  --repo reg.ivolve.cloud/ivolve/revease --tag v2 --service worker
```

api and worker build fine under qemu emulation (slow: ~10 and ~40 min). **The web
image does not** — Node segfaults inside `next build` under qemu. Build it natively
on the x86 host and bring it back to push with the Mac's saved login:

```bash
rsync -az --delete --exclude .git --exclude node_modules --exclude .next --exclude .venv \
  --exclude __pycache__ --exclude data --exclude "*.sqlite*" --exclude .env ./ ivolve_cloud:~/apps/revease/src/
ssh ivolve_cloud 'cd ~/apps/revease/src && docker build -f infra/docker/web.Dockerfile \
  --build-arg NEXT_PUBLIC_API_BASE=/api -t reg.ivolve.cloud/ivolve/revease:web-v2 .'
ssh ivolve_cloud 'docker save reg.ivolve.cloud/ivolve/revease:web-v2' | podman load
podman push reg.ivolve.cloud/ivolve/revease:web-v2
```

## The live deployment

The ivolve cloud deployment does not use this compose file — it has its own
(single public port, private registry, backups) under
[infra/ivolve/](infra/ivolve/README.md). Read that before touching the host.

## Run on another system

Only Docker + this repo's `docker-compose.prod.yml` and `.env` are needed — the
images are pulled from Docker Hub.

```bash
cp .env.docker.example .env        # add your ANTHROPIC key etc.
TAG=v1 docker compose -f docker-compose.prod.yml up -d
```

Open **http://localhost:3000**.

### Accessing from another machine (LAN / remote)

The browser calls the API directly, so the API URL is baked into the web image at
build time. For anything other than same-host access, rebuild web with the host's
address and push:

```bash
python shift.py --service web --tag v1 --api-base http://192.168.1.50:8000
# then on the host, set CORS to match and restart:
#   CORS_ORIGINS=http://192.168.1.50:3000  in .env
TAG=v1 docker compose -f docker-compose.prod.yml up -d
```

## Build from source instead of pulling

```bash
docker compose -f docker-compose.prod.yml build      # uses infra/docker/*.Dockerfile
docker compose -f docker-compose.prod.yml up -d
```

## Notes

- **TTS model**: the worker downloads the ~350MB Kokoro model into the volume on
  first start. Set `REFRACT_FETCH_KOKORO=0` to skip it (falls back to Piper, keyless).
- **No API key**: LLM labeling and TTS both degrade gracefully (offline labeler +
  silent/Piper audio), so the stack runs without any keys.
- **Data**: everything persists in the `refract-data` volume. `docker compose down`
  keeps it; add `-v` to wipe.
- **GPU whisper**: set `REFRACT_WHISPER_DEVICE=cuda` and run the worker on a CUDA
  host (add the NVIDIA runtime to the worker service).


## Switching the ivolve deployment to object storage + Postgres

The compose file already defines `minio` and `postgres`, and the edge proxies `/s3/` to MinIO. Nothing changes until `.env` opts in. Stop writes first (`docker compose stop api worker worker-light`), then:

```bash
# 1. start storage + database
docker compose up -d minio postgres
# 2. .env: add
#    REFRACT_STORAGE_BACKEND=s3
#    REFRACT_S3_ENDPOINT_URL=http://revease-minio:9000
#    REFRACT_S3_PUBLIC_URL=/s3
#    REFRACT_S3_ACCESS_KEY=<S3_ACCESS_KEY>   REFRACT_S3_SECRET_KEY=<S3_SECRET_KEY>
#    REFRACT_DATABASE_URL=postgresql+psycopg://revease:<POSTGRES_PASSWORD>@revease-postgres:5432/revease
# 3. copy existing media + rows (both are re-runnable / refuse to double-copy)
docker compose run --rm api python -m app.storage_migrate --from /data/media
docker compose run --rm api python -m app.dbcopy --source sqlite:////data/refract.sqlite3 \
  --target postgresql+psycopg://revease:<POSTGRES_PASSWORD>@revease-postgres:5432/revease
# 4. bring everything back
docker compose up -d
```

Keep `data/` until you've checked projects play and export; it is the rollback (remove the three settings and restart).
