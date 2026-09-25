# RevEase on ivolve cloud

The live deployment. Host `13.204.129.141` (`ssh ivolve_cloud`), deploy root
`~/apps/revease`. **URL: http://13.204.129.141:8020** (see "Why one port" for who
can reach it). Running **v4** (2026-09-25; v3 since 2026-09-24): object storage (MinIO), Postgres,
separate media/light workers, live progress, AI documentation.

This directory is the source of truth for everything except `.env` (secrets) and
`src/` (the rsynced source). The deploy root mirrors it:

```
~/apps/revease/
  docker-compose.yml   ← infra/ivolve/docker-compose.yml
  edge/nginx.conf      ← infra/ivolve/edge/nginx.conf
  build.sh             ← infra/ivolve/build.sh
  backup.sh            ← infra/ivolve/backup.sh   (cron: 02:30 daily)
  README.md            ← infra/ivolve/README.md   (this file)
  .env                 secrets + settings, chmod 600 (.env.bak-v2 = pre-v3 copy)
  .pre-v3/             the v2 compose / nginx / backup files, kept for rollback
  src/                 rsynced from this repo; build context only
```

## Services

| container | image | role |
|---|---|---|
| `revease-edge` | nginx:1.27-alpine | the single entry point (8090 in the container, 8020 on the host) |
| `revease-web` | `reg.ivolve.cloud/ivolve/revease:web-v4` | Next.js UI |
| `revease-api` | `…:api-v4` | FastAPI (also `127.0.0.1:8021` for curl on the host) |
| `revease-worker` | `…:worker-v4` | queue `media`, 1 at a time: convert, transcribe, render, auto-edit |
| `revease-worker-light` | `…:worker-v4` | queue `default`, 3 at a time: documents, snapshots, voice previews; runs Celery beat (hourly retention) |
| `revease-minio` | `reg.ivolve.cloud/ivolve/minio:RELEASE.2025-09-07T16-13-09Z` (mirrored; quay.io now refuses pulls) | media bucket `revease-media` (console on `127.0.0.1:8023`) |
| `revease-postgres` | postgres:16-alpine | the database |
| `revease-redis` | redis:7-alpine | Celery broker |

Volumes: `revease_minio-data` (all media), `revease_postgres-data` (the database),
`revease_revease-data` (Kokoro TTS model, the ffmpeg media cache under `cache/`,
and the pre-v3 SQLite file + media, kept as the rollback), `revease_redis-data`.

## Why one port

Of this host's ports only **80 and 443 reach the internet** — both owned by
nginx-proxy-manager. `8020` is published by docker and answers on the host, but the
security group drops it from outside (measured 2026-08-27). 3000 and 8000 are
taken locally by gitea and flowwatcher. So the `edge` container serves everything
from one origin:

| path | upstream |
|---|---|
| `/` | web (Next.js :3000) |
| `/api/…` | api (FastAPI :8000, prefix stripped) |
| `/s3/…` | MinIO :9000 (prefix stripped, `Host: revease-minio:9000`) |

**The only public path in is nginx-proxy-manager → `revease-edge:8090`.**

Because everything shares an origin, `WEB_API_BASE` is origin-relative (`/api`)
and `REFRACT_S3_PUBLIC_URL` is `/s3`, so one web image serves any hostname with no
rebuild and CORS is never involved.

**Why `/s3/` forces that Host header.** Media URLs are S3 presigned URLs, signed
by the API against `http://revease-minio:9000`. SigV4 signs the host and path, so
the edge must forward exactly `Host: revease-minio:9000` and `/<bucket>/<key>` or
MinIO rejects the signature. The upstream is resolved per request, so the edge
still starts if MinIO is down. The edge proxies to **container names**
(`revease-api`, `revease-web`, `revease-minio`): on `ivolve-network` other stacks
already own the names `api` and `web`.

## How media flows

- **Uploads**: the browser splits large files into 16 MB parts and PUTs them in
  parallel straight to `/s3/` (presigned), resuming after a dropped connection.
  The API only signs parts and completes the upload. No request-size limit
  applies; nothing is buffered.
- **Playback/downloads**: the UI requests `/api/media/<key>`; the API answers
  `307` to a presigned `/s3/…` URL. Range requests (video seeking) work.
- **Workers** download what ffmpeg needs into `/data/cache` (shared by the
  containers on this host, LRU-capped at 20 GB) and upload results.
- **Downloads of the original recording**: Download menu on the prepare page and
  capture cards (`GET /api/sessions/<id>/download`).

## HTTPS via nginx-proxy-manager

**Screen capture does not work over plain HTTP.** `getDisplayMedia` /
`getUserMedia` are secure-context only, so the in-app recorder is dead on
`http://…:8020` — upload, editing, documents and render are fine. Everything on
this host's side is ready:

- `edge` is on `ivolve-network` alongside `nginx-proxy-manager-app-1`, and
  `docker exec nginx-proxy-manager-app-1 curl -s http://revease-edge:8090/api/healthz`
  answers `{"status":"ok"}`.
- The web bundle and media URLs are origin-relative, so they work on the new
  hostname with no rebuild.

**The only missing piece is DNS:** `revease.ivolve.cloud` has no A record. Add
`revease A 13.204.129.141` in the ivolve.cloud zone, then add one proxy host in NPM
(admin UI on `127.0.0.1:81`; tunnel with `ssh -N -L 8181:127.0.0.1:81 ivolve_cloud`):

| field | value |
|---|---|
| Domain Names | `revease.ivolve.cloud` |
| Scheme | `http` |
| Forward Hostname | `revease-edge` (container name) |
| Forward Port | `8090` (container-internal, **not** the published 8020) |
| Websockets Support | on |
| Block Common Exploits / Cache Assets | off |

SSL tab: request a Let's Encrypt cert, Force SSL, HTTP/2. Advanced tab (NPM
buffers and caps bodies by default, which breaks uploads and video seeking):

```nginx
client_max_body_size 0;
proxy_request_buffering off;
proxy_buffering off;
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
```

Only **one** proxy host: `edge` already splits `/`, `/api/` and `/s3/`. Then add
the https origin to `CORS_ORIGINS` in `.env` (only the extension needs it).

## Images

Built **on this host** (x86, native — far faster than emulating from an
Apple-silicon Mac, and Next.js segfaults under qemu) and pushed to Gitea's
container registry `reg.ivolve.cloud` under the `ivolve` org:

```
reg.ivolve.cloud/ivolve/revease:api-v4
reg.ivolve.cloud/ivolve/revease:worker-v4   (ffmpeg + faster-whisper)
reg.ivolve.cloud/ivolve/revease:web-v4
```

The host is `docker login`ed to `reg.ivolve.cloud` as `karthik`. `.env` sets
`REGISTRY` and `IMAGE_NS` to `reg.ivolve.cloud/ivolve/revease` and `TAG=v4` (v3 images stay in the registry for rollback: set `TAG=v3`, `docker compose up -d`).
(Earlier versions used a private `registry:2` on `localhost:5000`; `v1`/`v2` images
are still in the local Docker cache.)

## Deploying a new version

From the repo root on your machine:

```bash
rsync -az --delete \
  --exclude .git --exclude node_modules --exclude .next --exclude .venv \
  --exclude __pycache__ --exclude data --exclude "*.sqlite*" --exclude .env --exclude .claude \
  ./ ivolve_cloud:/home/ubuntu/apps/revease/src/
```

Then on the host:

```bash
cd ~/apps/revease
cp src/infra/ivolve/{docker-compose.yml,backup.sh,build.sh,README.md} .   # if they changed
cp src/infra/ivolve/edge/nginx.conf edge/nginx.conf                        # if it changed
./build.sh            # all three (tag from .env); or ./build.sh web|api|worker
docker compose up -d
docker exec revease-edge nginx -s reload   # only if nginx.conf changed
```

**Before restarting the media worker, check nothing long is converting**
(header activity menu, or
`docker exec revease-postgres psql -U revease -tAc "select stage,message from jobs where status='running'"`).
A restart interrupts it; the task message then sits unacknowledged in Redis for
the 12 h visibility timeout. To resume immediately:

```bash
for t in $(docker exec revease-redis redis-cli HKEYS unacked); do
  docker exec revease-redis redis-cli HDEL unacked "$t"; docker exec revease-redis redis-cli ZREM unacked_index "$t"; done
docker compose exec -T api python -c "from app.queue import enqueue_understanding; enqueue_understanding('<session id>')"
```

The new request waits until the interrupted run's heartbeat is 3 minutes stale,
then takes over.

`WEB_API_BASE` is compiled into the web bundle, so changing it needs
`./build.sh web`, not a restart.

## Operations

```bash
docker compose ps
docker compose logs -f api worker worker-light
curl -s localhost:8020/api/healthz
docker compose exec -T api python -m app.retention --dry-run    # what the hourly sweep would delete
```

- **Progress**: every long job reports progress; `GET /api/activity` is what the
  header indicator shows.
- **Retention** (hourly, `worker-light`): originals 7 days after a processed MP4
  exists, transcription audio 2 days, superseded renders 7 days, TTS cache 30
  days, abandoned uploads 24 h. Tune with `REFRACT_RETENTION_*` in `.env`.
- **MinIO console**: `ssh -N -L 8023:127.0.0.1:8023 ivolve_cloud`, then
  http://localhost:8023 (user `revease`, password `S3_SECRET_KEY` in `.env`).

**Backups** — `backup.sh` runs nightly at 02:30 into `~/apps-data/revease-backups/`,
keeping 7 of each: `revease-<date>-db.pgdump` (pg_dump custom format) and
`revease-<date>-media.tar.gz` (the MinIO volume). It follows `.env`, so it backs up
SQLite and local media instead if those are configured. Restore commands are in
the script header. The final pre-v3 archive is `revease-2026-09-24.tar.gz`.

## The v3 switch-over (2026-09-24) and rollback

Done with writers stopped: `app.storage_migrate` copied `/data/media` into the
bucket (1,440 files, 911 MB) and `app.dbcopy` copied SQLite into Postgres (1,633
rows; counts verified table by table). Keys and ids are unchanged.

Rollback to v2 (loses anything created after the switch):

```bash
cd ~/apps/revease
cp .pre-v3/docker-compose.yml .pre-v3/backup.sh . && cp .pre-v3/nginx.conf edge/nginx.conf
cp .env.bak-v2 .env
docker compose up -d --remove-orphans && docker exec revease-edge nginx -s reload
```

## Verified

- **2026-09-24 (v3)**: health and web through the edge; presigned media through
  `/s3/` (307 → 200) and video Range (206); both workers on their queues, beat
  running; the in-flight 29-minute recording resumed on the new media worker,
  fetching its source from MinIO. The full browser flow (162 MB resumable upload →
  processing → 20-step document → DOCX → render) was verified against the same
  MinIO/Postgres setup locally, since the public URL is not reachable from outside.
- **2026-08-25 (v1)**: upload → understanding → graph → render through the edge;
  re-rendering unchanged scenes reuses all clips.

## AI provider

AI runs through **OpenRouter** (`REFRACT_OPENROUTER_API_KEY`, model
`REFRACT_OPENROUTER_MODEL`, default `anthropic/claude-opus-4.1`) for step labels,
project titles, documentation, script rewriting and zoom suggestions.
`REFRACT_ANTHROPIC_API_KEY` is empty on purpose — set it only with a real
Anthropic key (`sk-ant-…`); it takes precedence when present.

Until v4 (2026-09-25) the OpenRouter key sat in `REFRACT_ANTHROPIC_API_KEY`:
every call failed with 401 and each feature silently used its offline fallback
(project names were the transcript's first words). The API now moves an `sk-or-`
key out of the Anthropic slot automatically. Check what is in use with:

```bash
docker compose exec -T api python -c "from app.llm import provider_name; print(provider_name())"
```

Spend and limit: https://openrouter.ai/settings/keys (the admin Usage page shows
it too once `REFRACT_OPENROUTER_MANAGEMENT_KEY` is set).

## Not configured

- No HTTPS yet: blocked on the `revease.ivolve.cloud` DNS record (see above).
- `DEFAULT_API_BASE` in `apps/extension/src/api.js` points at
  `http://13.204.129.141:8020/api`; switch it to the https URL once the domain
  resolves.
