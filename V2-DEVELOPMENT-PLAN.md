# Refract — Gap Analysis & Development Plan (V1 → full Master Plan)

> Reconciles what's **built today** against `files (5)/00-MASTER-PLAN.md` (Phases 0–10) and lays out
> the remaining work as sequenced development tracks. V1 (`V1-CORE-PLAN.md`, P0–P3) is done; this is
> the road to the full product.

---

## 1. What's built today (V1 + extras)

| Area | Status |
|---|---|
| Monorepo `apps/{web,api,workers,extension}` + `packages/workflow-graph` | ✅ |
| Capture: in-app recorder, MV3 extension, upload | ✅ |
| Understanding pipeline → schema-valid Workflow Graph (ffmpeg frames, Whisper, segment, Claude extract) | ✅ |
| `buildTimeline` (drift-free) + FFmpeg render + **regenerate only changed segments** | ✅ |
| Editor (Script/Zooms/Scenes/Captions), filler removal, trim | ✅ |
| Voice: Piper (local, keyless) + OpenAI + silent, behind one adapter | ✅ |
| LLM: Claude via Anthropic SDK (OpenRouter fallback) | ✅ |
| UI: sidebar shell, Projects/Library, thumbnail posters | ✅ |
| Persistence: **SQLite** + local filesystem media (presigned-style interface) | ✅ (single-user) |

**Tables today:** projects, capture_sessions, events, media_assets, transcripts, workflow_graphs,
video_projects, render_jobs, jobs. **No** users/workspaces/memberships.

---

## 2. Gap analysis vs Master Plan

Legend: ✅ done · 🟡 partial/trimmed · ❌ missing

| Master phase | Feature | Status | Notes |
|---|---|---|---|
| 0 Foundation | Monorepo, DB, storage, jobs | 🟡 | SQLite + local FS, not Postgres/pgvector/MinIO |
| 0 Foundation | **Auth, users, workspaces, RBAC** | ❌ | Single-user, no login |
| 0 Foundation | **CI/CD, Docker per app, k8s** | ❌ | Only `infra/docker/` stub + compose(redis); no `.github` |
| 0 Foundation | Observability (OTel), cost ledger | ❌ | Structured logging only |
| 1 Capture | Recorder / extension / upload | ✅ | |
| 1 Capture | **Cloud imports** (Drive/OneDrive/Dropbox/Loom/Zoom) | ❌ | |
| 1 Capture | Library ingest surface | ✅ | Library page added |
| 2 Understanding | Frames + Whisper + segment + Claude graph | ✅ | |
| 2 Understanding | **OCR (PaddleOCR)** screen naming | ❌ | |
| 2 Understanding | **CV click-detection fallback** (OpenCV/YOLO) | ❌ | Uploads w/o telemetry → scene fallback only |
| 2 Understanding | **PII redaction + screenshot blur** | 🟡 | Password masking at capture only; no full pass |
| 2 Understanding | Vision calls for ambiguous keyframes | ❌ | |
| 3 Docs | **SOP/guide/FAQ/assessment** generation | ❌ | The deferred V1-P4 |
| 3 Docs | Annotated screenshots, doc editor (Tiptap) | ❌ | |
| 3 Docs | **Exports MD/PDF/DOCX/HTML**, Confluence/Notion | ❌ | |
| 4 Video | Editor + FFmpeg render + regenerate | ✅ | |
| 4 Video | Live-video-motion segments (vs stills), zoom ease-in | 🟡 | Render uses still+zoompan; motion is a refinement |
| 4 Video | AI avatar (talking head) | ❌ | |
| 5 Voice/Brand | Minimal TTS adapter | ✅ | Piper/OpenAI/silent |
| 5 Voice/Brand | Multi-provider (ElevenLabs/Azure/XTTS), cloning, **BYO key** | ❌ | |
| 5 Voice/Brand | **Brand Kit** (avatars/backgrounds/logos/music) | ❌ | |
| 5 Voice/Brand | Glossary + pronunciations | ❌ | |
| 6 Interactive | Hotspots/tooltips/branching + embeddable player | ❌ | No `apps/player` |
| 7 Translation | Translate script/voice/captions/docs | ❌ | |
| 8 Publish | **Share/viewer pages, download, embed** | ❌ | |
| 8 Publish | Shared-Pages analytics (views, watch time) | ❌ | |
| 9 Ask AI | **RAG index + Ask AI + Knowledge Base** | ❌ | pgvector/Qdrant not present |
| 10 Enterprise | Skills presets (video/doc) | ❌ | |
| 10 Enterprise | **Billing + AI-minute metering** | ❌ | |
| 10 Enterprise | **Project memory (re-record + diff)** — top moat | ❌ | Graph versioning exists; diff/re-record loop doesn't |
| 10 Enterprise | SSO (SAML), audit, on-prem | ❌ | |
| 10 Enterprise | Library folders, workspace admin | 🟡 | Flat Library only |

---

## 3. Development tracks (the missing work, grouped)

Each track is independently valuable. Effort in **ed** = experienced engineer-days driving Claude Code
(same unit as the master plan).

### Track A — Productionization & Multi-tenancy  ·  ~12 ed
*Prereq for anything shared with real users.*
- **A1 Auth**: OAuth (Google/MS/GitHub) + email, JWT sessions; protect API routes.
- **A2 Workspaces/RBAC**: users, workspaces, memberships, roles `owner|admin|editor|viewer`; scope every entity to a workspace; invites.
- **A3 Postgres + pgvector**: migrate SQLite→Postgres, Alembic migrations; keep the data layer, swap the engine. (pgvector prepped for Track H.)
- **A4 Object storage**: drop MinIO/S3 in behind the existing presigned interface (real presigned PUT/GET); lifecycle rule for raw frames.
- **A5 CI/CD + Docker**: Dockerfile per app, full `docker-compose`, GitHub Actions (lint/typecheck/test/build).
- **A6 Observability**: OpenTelemetry traces API→Celery→LLM, structured JSON logs, per-session **cost ledger** (LLM tokens, TTS chars, GPU-min).

### Track B — Understanding fidelity  ·  ~9 ed
- **B1 OCR** (PaddleOCR) per keyframe → screen names/labels; feed into extraction.
- **B2 CV click-detection fallback** (OpenCV cursor/ripple; optional YOLO UI elements) so plain uploads get click-precise steps.
- **B3 Full PII pass**: detect emails/tokens/cards in OCR+transcript, redact **before** any LLM/share; screenshot blur regions.
- **B4 GPU Whisper** production path (CUDA 12.x on the RTX 5070) + vision calls for ambiguous keyframes.

### Track C — Docs & exports (Phase 3, deferred V1-P4)  ·  ~8 ed
- **C1 SOP/guide** generation from the graph (numbered steps + best keyframe per step).
- **C2 FAQ + Assessment** generators.
- **C3 Annotated screenshots** (highlight bbox, blur regions from B3).
- **C4 Doc editor** (Tiptap) over the generated doc.
- **C5 Exports**: Markdown + PDF (then DOCX/HTML); Confluence/Notion push.

### Track D — Brand & Voice (Phase 5 full) + render fidelity  ·  ~10 ed
- **D1 Multi-provider TTS**: ElevenLabs/Azure/XTTS + per-workspace fallback policy; cost ledger hook.
- **D2 Custom/cloned voice + BYO key** (encrypted at rest, redacted from logs).
- **D3 Brand Kit**: voices, avatars, backgrounds, logos, music library; auto-apply to new videos.
- **D4 Glossary + pronunciations** (SSML/lexicon at TTS build time; glossary into the rewrite prompt).
- **D5 Render fidelity**: live-video-motion segments (trim/hold real video, not just stills), zoom ease-in/out, music ducking polish, AI-avatar overlay.

### Track E — Publish, share, analytics (Phase 8)  ·  ~8 ed
- **E1 `apps/player`**: embeddable video + (later) interactive-demo player SDK.
- **E2 Share/viewer pages**: public links, download, embed code; access controls.
- **E3 Shared-Pages analytics**: views, total/avg watch time, per-asset rows.

### Track F — Interactive demos (Phase 6)  ·  ~9 ed
- **F1** Hotspots/tooltips/branching editor (React Flow over the graph's conditional edges).
- **F2** Embeddable interactive player (extends E1).

### Track G — Translation & language (Phase 7)  ·  ~6 ed
- Translate script/captions/docs; re-synth voice per language; language selector; per-language render variants (reuses the regenerate loop).

### Track H — Ask AI & Knowledge Base (Phase 9)  ·  ~8 ed
- **H1** Embed + index all assets (pgvector → Qdrant at scale).
- **H2** Ask AI assistant with cited answers (Workflow-Graph step IDs as citations).
- **H3** Knowledge Base CRUD/search/grouping.

### Track I — Enterprise & the moats (Phase 10)  ·  ~14 ed
- **I1 Project memory (flagship)**: re-record a workflow → **diff graph versions** → mark changed steps dirty → regenerate only changed sections of every output. Builds directly on existing graph versioning + the P3 dirty-segment regenerate loop.
- **I2 Skills presets** (Video/Doc output presets).
- **I3 Billing + AI-minute metering** (on top of A6 cost ledger).
- **I4 SSO (SAML), audit logs, on-prem packaging**; Library folders + workspace admin UI.

---

## 4. Recommended milestone sequencing

Critical-path first; each milestone is independently shippable.

**M1 — Shareable Beta (~20 ed).** Track C (docs/export) + Track B3 (PII) + Track E (share/analytics) +
minimum of Track A (A1 auth, A3 Postgres, A4 storage). → "record → video **and** doc → share a link,"
safely, with logins. Highest value per day; unlocks real users.

**M2 — Understanding + Brand (~15 ed).** Rest of Track B (OCR/CV/GPU) + Track D (brand kit, cloned/BYO
voice, render fidelity). → on-brand, higher-fidelity output.

**M3 — Differentiators (~20 ed).** **Track I1 project memory** (the durable moat) + Track F interactive
demos + Track G translation.

**M4 — Scale & Enterprise (~20 ed).** Track H (Ask AI/KB) + Track A5/A6 hardening (CI, OTel, cost) +
Track I2–I4 (skills, billing, SSO, on-prem).

Total remaining ≈ **75–85 ed** to full Phase-10 parity (matches the master plan's post-beta scope).

---

## 5. Cross-cutting hardening (do alongside, not a phase)
- **Tests**: integration per endpoint, an E2E happy-path, expand render/timeline edge cases.
- **Jobs**: dead-letter surfacing + retry/backoff audit (idempotency already keyed `(session,stage,version)`).
- **Progress**: replace status **polling** with Redis pub/sub → WebSocket (master §2 E5).
- **Security**: rate limiting, secret rotation, encrypt BYO keys, PII before any share (Track B3 gates sharing).
- **Cost controls**: adaptive frame sampling (have ~1fps), compact events to LLM (have), render-on-export (have); add the cost ledger (A6) to enforce §5 targets.

---

## 6. Suggested immediate next steps (single dev + Claude Code)
1. **Track C (Docs & export)** — cheapest, high-visibility win off the existing graph; ships "video ⇄ document."
2. **Track B3 (PII) + B1 OCR** — correctness/safety; also feeds annotated screenshots in C3.
3. **Track A (A1/A3/A4)** — only when you're ready to put it in front of others; everything shareable depends on it.
4. **Track I1 (Project memory)** — the flagship differentiator; do it once the graph pipeline is stable (it is).

> Reuse the original `PHASE-03/05/06/07/08/09/10-*.md` files as detailed work orders — nothing built in
> V1 needs redoing, only extending; the Workflow Graph + `buildTimeline` remain authoritative.
