# Refract V1 Build Progress

Video-only V1 (P4 doc export deferred to V2). Tick items only when the phase exit criteria pass.

- [x] **V1-P0 — Lean foundation**
  - [x] E1 Trimmed monorepo (web, api, workers, extension, packages/workflow-graph)
  - [x] E2 Local persistence (SQLite + data layer) + local media store (presigned-style)
  - [x] E3 `make dev` runs web+api+worker; `.env.example`; `/healthz`
  - **Exit:** ✅ stack runs locally; IR validator passes on the master §2 example (TS 5/5, Py 5/5); project create/read verified over HTTP; Celery ping round-trips `pong`
- [x] **V1-P1 — Capture**
  - [x] E1 In-app recorder (getDisplayMedia + mic, countdown, pause/resume, timer) + page-level click/input log (password-masked)
  - [x] E2 Extension (MV3): click/input(redacted)/navigation + throttled screenshots, IndexedDB buffer, upload → session
  - [x] E3 Upload (mp4/webm) drag-drop + ingest; sessions with no events flagged `telemetry=absent`
  - [x] E4 Capture list on the project page (source, status, telemetry badge)
  - **Backend:** `POST /sessions`, `/sessions/{id}/assets` (presigned-style), `/sessions/{id}/events` (validated), `/sessions/{id}/complete`, `GET /sessions`, `GET /sessions/{id}`, `PUT|GET /media/{key}`
  - **Verified:** api tests 8/8; web typecheck clean; extension JS syntax-checked; full extension HTTP flow (20-step log + screenshot → `telemetry=present`, media round-trips) proven against a live API
  - **Note:** recorder click log only sees clicks in its own tab (documented V1 limit); the extension is the full cross-site click path. Browser-driven record/upload UI needs manual verification in a real browser.
- [x] **V1-P2 — AI understanding → Workflow Graph**
  - [x] E1 FFmpeg scene-change frames (~1fps cap) + audio demux; Whisper word-level transcript behind an adapter (faster-whisper when installed, empty-transcript fallback otherwise)
  - [x] E2 Merge + segment: click-boundary steps (telemetry present) / transcript-sentence / scene-keyframe fallback (absent); nearest keyframe + transcript span, leading/trailing narration attached
  - [x] E3 Extraction (understand→validate→compose nodes) via LLM adapter (OpenRouter/Claude when keyed, deterministic labeler fallback) → schema-valid graph, persisted & versioned
  - [x] E4 Orchestration: enqueue on `/complete`; per-stage Job rows keyed `(session,stage,version)`; idempotent (graph upsert by project+version); Celery retries w/ backoff; readable errors; `GET /sessions/{id}/status` progress + `POST /sessions/{id}/reprocess`
  - **Endpoints:** `GET /sessions/{id}/status`, `POST /sessions/{id}/reprocess`, `GET /projects/{id}/graph?version=`
  - **Web:** session detail page — live stage-status dots + generated Workflow Graph steps (screenshot, action→target, narration, timings)
  - **Verified:** workers tests 13/13 (segmentation edge cases, extraction contract, idempotency, **real-ffmpeg** frame extraction, eager full pipeline); full suite 31/31; **live broker E2E**: capture → `/complete` → Celery worker ran media/whisper/merge/extract → `ready v1` → 5 click-segmented narrated schema-valid steps fetched from `/graph`
  - **Deferred to V2 (per plan):** OCR screen-naming, CV click-detection fallback, full PII pass, cost ledger (rough logs only)
  - **Whisper enabled by default:** `make install` runs `uv sync --extra whisper`; the adapter transcribes on CPU (model auto-downloads; set `REFRACT_WHISPER_DEVICE=cuda` on the RTX 5070 for speed). Tests force `REFRACT_DISABLE_WHISPER` for determinism.
  - **Fixes (post-P3):** keyframe extraction fps-cap bug (`mod(n,1)` selected every frame → thousands of steps) fixed to fixed `fps=1` + `max_frames`; scene segmentation capped at 20 steps; additive SQLite auto-migration in `init_db` (preserves local data).
- [x] **V1-P3 — Video generation, editor & regenerate loop**
  - [x] E0 `buildTimeline` pure module — output clock from per-step TTS durations (no drift by construction), click-centered zoom, source windows; **12/12 exhaustive edge-case tests** (empty / no clicks / back-to-back / zero-duration / leading+trailing narration / coord OOB / reversed window / fast+slow speed)
  - [x] E1 `TTSProvider` adapter — OpenAI TTS default + silent-clip fallback (offline), per-step synth `{audio,duration_ms}`, cached by `(text_hash,voice_id,speed,provider)`, speed control
  - [x] E2 Editor (`/projects/{id}/video`): Script/Zooms/Scenes/Captions tabs; timestamped editable script; **filler-word removal** (struck, click-to-toggle, re-flow); Save + Generate
  - [x] E3 Zooms — auto per-click marker (center from graph bbox), per-segment enable + scale nudge
  - [x] E4 Scenes/captions/frame — intro/outro title cards, burned captions, aspect switch (16:9/9:16/1:1)
  - [x] E5 Render (FFmpeg-first): per-segment still (screenshot or video frame) + click-centered zoom + per-step TTS + burned caption → concat → intro/outro; **render on export only**
  - [x] E6 Regenerate loop: per-clip content-hash cache → editing re-synthesizes + re-renders **only changed segments**, reuses the rest
  - **Endpoints:** `GET/PATCH /projects/{id}/video`, `POST /projects/{id}/video/render`, `GET /render/{job}`
  - **Verified:** render test + full suite **44/44**; **live broker E2E (release gate)**: upload video → understanding → 3-step graph → edit-spec → render MP4 (6.68s vs expected 6.58s, **drift < 0.11s**) → edit one segment's script → regenerate **rendered 1 / reused 2, TTS synth 1 / cached 2**
  - **Note:** offline here → silent TTS + still-image segments (screenshot/video-frame). Real voiceover needs `REFRACT_OPENAI_API_KEY`; live-video-motion segments (vs stills) and zoom ease-in are V2 refinements.

---

## 🎉 V1 core loop complete — capture → AI video → edit → regenerate → drift-free MP4
Release-gate checklist (§5) all satisfied except the two provider-key items (Whisper GPU, OpenAI TTS), which are wired behind adapters and just need keys/hardware.

## Providers (post-P3)
- **LLM:** step labeling/narration calls Claude via the official Anthropic SDK (`claude-opus-4-8`, `REFRACT_ANTHROPIC_API_KEY`); falls back to OpenRouter, then a deterministic offline labeler. Verified: bad key → graceful 401 fallback.
- **Voice:** default is **Piper** — keyless local neural TTS (`REFRACT_TTS_PROVIDER=piper`, model auto-downloads ~63MB to `data/piper/`). Verified real speech synthesis. `openai` and silent-clip paths remain behind the same adapter.
- **Config fix:** `Settings` now loads the **repo-root `.env`** regardless of CWD (api/worker run from `apps/*`), so `.env` keys actually take effect. All provider/whisper/tts config flows through `get_settings()`.

## Notes / environment
- **No NVIDIA GPU visible** in the current dev shell — Whisper will fall back to CPU (slow) in P2 until CUDA 12.x is set up on the RTX 5070 target.
- TTS: OpenRouter has no TTS endpoint; voice uses OpenAI TTS behind the `TTSProvider` adapter (swappable).
- ffmpeg 4.4.2 present; Python 3.12 via `uv`; Node 20 + npm; Redis via Docker.
