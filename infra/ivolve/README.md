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

Of this host's ports only **80 and 443 reach the internet** — both owned by
nginx-proxy-manager. `8020` is published by docker and answers on the host, but the
security group drops it from outside (measured 2026-08-27; the earlier note here
claiming 8020 was open was wrong). 3000 and 8000 are taken locally by gitea and
flowwatcher. So an nginx `edge` container listens on 8090, is published to the host
as 8020 for local curl, and serves both halves from one origin:

| path | upstream |
|---|---|
| `/` | web (Next.js :3000) |
| `/api/…` | api (FastAPI :8000, prefix stripped) |

**The only public path in is nginx-proxy-manager → `revease-edge:8090`.**

The API is also on `127.0.0.1:8021` for curl on the host. Same origin means CORS
is not involved in normal use.

Because both halves share an origin, `WEB_API_BASE` is **origin-relative** (`/api`),
not an absolute URL. One web image therefore serves every hostname the stack is
reached by — the IP:8020 URL today, a domain in front of it tomorrow — with no
rebuild. Put an absolute URL there only if web and API are ever split apart.

## HTTPS via nginx-proxy-manager

**Screen capture does not work over plain HTTP.** `getDisplayMedia` /
`getUserMedia` are secure-context only, so `Recorder.tsx` and `CaptureModal.tsx`
are dead on `http://…:8020` — upload, editing and render are fine. Everything on
this host's side is ready:

- `edge` is on `ivolve-network` alongside `nginx-proxy-manager-app-1`, and
  `docker exec nginx-proxy-manager-app-1 curl -s http://revease-edge:8090/api/healthz`
  already answers `{"status":"ok"}`.
- The web bundle uses a relative `/api`, so it works on the new hostname with no
  rebuild.

**The only missing piece is DNS:** `revease.ivolve.cloud` has no A record. Add
`revease A 13.204.129.141` in the ivolve.cloud zone (same as every other app
there), then add one proxy host in NPM — admin UI is on `127.0.0.1:81`, not
reachable from outside, so tunnel with `ssh -N -L 8181:127.0.0.1:81 ivolve_cloud`:

| field | value |
|---|---|
| Domain Names | `revease.ivolve.cloud` |
| Scheme | `http` |
| Forward Hostname | `revease-edge` (container name) |
| Forward Port | `8090` (container-internal, **not** the published 8020) |
| Websockets Support | on |
| Block Common Exploits / Cache Assets | off |

SSL tab → request a new Let's Encrypt cert, Force SSL, HTTP/2. Advanced tab needs
this, because NPM's global `client_max_body_size` is 2000m and it buffers by
default — which would break streamed recording uploads and Range video playback:

```nginx
client_max_body_size 0;
proxy_request_buffering off;
proxy_buffering off;
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
```

Only **one** proxy host — `edge` already splits `/` and `/api/` internally. Note
the pattern other apps here follow: `usagetrackerapp.ivolve.cloud` forwards to
`usage-tracker-frontend:80`, the *container* port, not the 3011 it is published on.

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
- No HTTPS yet — blocked on the `revease.ivolve.cloud` DNS record (see above).
- `DEFAULT_API_BASE` in `apps/extension/src/api.js` still points at
  `http://13.204.129.141:8020/api`. The extension is a separate origin and cannot
  use a relative base, so it stays absolute; switch it to the https URL once the
  domain resolves. The account page shows the right value to paste — it resolves
  the relative base against whatever origin the UI was loaded from.
