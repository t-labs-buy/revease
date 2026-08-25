# RevEase on ivolve cloud

The live deployment. Host `13.204.129.141` (`ssh ivolve_cloud`), deploy root
`~/apps/revease`. **URL: http://13.204.129.141:8020**

This directory is the source of truth for everything except `.env` (secrets) and
`src/` (the rsynced source). The deploy root mirrors it:

```
~/apps/revease/
  docker-compose.yml   ← infra/ivolve/docker-compose.yml
  edge/nginx.conf      ← infra/ivolve/edge/nginx.conf
  build.sh             ← infra/ivolve/build.sh
  backup.sh            ← infra/ivolve/backup.sh   (cron: 02:30 daily)
  .env                 ← infra/ivolve/.env.example, filled in + chmod 600
  src/                 rsynced from this repo; build context only
```

## Why one port

Only 80, 443 and 8020 reach this host from outside, and 80/443 belong to
nginx-proxy-manager. 3000 and 8000 are taken locally by gitea and flowwatcher. So
an nginx `edge` container owns 8020 and serves both halves from one origin:

| path | upstream |
|---|---|
| `/` | web (Next.js :3000) |
| `/api/…` | api (FastAPI :8000, prefix stripped) |

The API is also on `127.0.0.1:8021` for curl on the host. Same origin means CORS
is not involved in normal use.

**Screen capture does not work over plain HTTP.** `getDisplayMedia` /
`getUserMedia` are secure-context only, so `Recorder.tsx` and `CaptureModal.tsx`
are dead on `http://…:8020` — upload, editing and render are fine. Fixing this
needs HTTPS. The plumbing is ready: `edge` is attached to `ivolve-network`, and
nginx-proxy-manager can already reach `revease-edge:8080` by name. What is missing
is a DNS A record for e.g. `revease.ivolve.cloud` → 13.204.129.141. Once it
resolves: add a proxy host in NPM (forward to `revease-edge` port 8080, request a
Let's Encrypt cert), set `WEB_API_BASE=https://revease.ivolve.cloud/api` and
`CORS_ORIGINS` to match in `.env`, then `./build.sh web && docker compose up -d`.

Note the edge config proxies to **container names** (`revease-api`, `revease-web`),
not the compose service names: joining `ivolve-network` puts it in a namespace
where other stacks already own the names `api` and `web`, and their DNS wins.

## Images

Built on the host and pushed to the host's own **private** registry — `registry:2`
on `localhost:5000`, htpasswd-protected (creds in `~/apps/docker-registry/.env`):

```
localhost:5000/revease:api-v1     464MB
localhost:5000/revease:worker-v1  2.24GB   (ffmpeg + faster-whisper)
localhost:5000/revease:web-v1     851MB
```

`reg.ivolve.cloud` is **not** this registry — that hostname is Gitea's container
registry (bearer-token auth, `<owner>/<image>` paths) and rejects the `admindoc`
htpasswd credentials.

## Deploying a new version

From the repo root on your machine:

```bash
rsync -az --delete \
  --exclude .git --exclude node_modules --exclude .next --exclude .venv \
  --exclude __pycache__ --exclude data --exclude "*.sqlite*" --exclude .env \
  ./ ivolve_cloud:/home/ubuntu/apps/revease/src/
```

Then on the host:

```bash
cd ~/apps/revease
./build.sh            # all three; or ./build.sh web / api / worker
docker compose up -d
```

`WEB_API_BASE` is compiled into the web bundle, so changing it in `.env` requires
`./build.sh web` — a restart alone does nothing.

## Operations

```bash
docker compose ps
docker compose logs -f api worker
curl -s localhost:8020/api/healthz
```

**Backups** — `backup.sh` runs nightly at 02:30 and writes
`~/apps-data/revease-backups/revease-<date>.tar.gz`, keeping 7. The SQLite DB goes
through sqlite3's online backup API (WAL mode + two writers means a plain file copy
can tear); `kokoro/` and `tts/` are excluded as regenerable. Restore by extracting
into the volume and renaming `_backup.sqlite3` to `refract.sqlite3`.

## Verified end to end (2026-08-25)

Upload → understanding → graph → render, driven through the edge proxy exactly as
the browser drives it: 4-step graph from a 15s narrated recording, whisper
transcript verbatim, render 4/4 segments in ~25s, 300KB mp4 out. Re-rendering with
nothing changed settles at `segments_reused: 4, tts_cached: 4` — but note the
*first* re-render reports `rendered 3 / reused 1` because motion-zoom thinning
changes the clip hashes once before it stabilises.

## Not configured

- `REFRACT_ANTHROPIC_API_KEY` is empty, so step labels and narration come from the
  deterministic offline labeler (`intent` reads "Interact with <transcript line>").
- No HTTPS (see above).
