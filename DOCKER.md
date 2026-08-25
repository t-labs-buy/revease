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
`--no-whisper` (lighter worker), `--platform linux/amd64,linux/arm64` (buildx).

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
