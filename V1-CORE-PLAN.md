# Refract V1 — Core Release Plan

> **V1 = one thing done well:** capture a workflow → AI generates a polished video → user edits → AI regenerates.
> Single-user, runs locally. No auth, no workspaces, no CI/CD, no sharing. Everything else is V2.

**Build agent:** Claude Code (Opus 4.8). **Supersedes** `00-MASTER-PLAN.md` for V1 scope only; the full phase files remain the reference for depth and for V2.

---

## 1. In scope (V1) vs deferred (V2)

**IN — the core loop**
- **Capture:** manual in-app screen recorder · video upload · browser-extension click telemetry.
- **AI understanding:** video → transcript (Whisper) + click telemetry → **Workflow Graph**.
- **AI generation:** studio video from the graph — filler words removed, TTS voiceover, telemetry-driven auto-zoom, captions, intro/outro.
- **Edit + regenerate:** editable script, filler toggles, zoom nudges, scenes → **regenerate only what changed**.
- **Minimal voice:** one TTS provider (behind a thin adapter). Not the full Brand Kit.
- Local persistence + media storage. Unit tests for the correctness-critical logic (timeline mapping).

**OUT — moved to V2** (see full phase files)
| Deferred | Was |
|---|---|
| Auth, workspaces, roles/RBAC, invites | Phase 0/10 |
| CI/CD pipeline, k8s, on-prem, SSO, audit | Phase 0/10 |
| Cloud imports (Drive/OneDrive/Dropbox/Loom/Zoom), Library folders | Phase 1/10 |
| CV click-detection fallback for plain uploads, PII blur | Phase 2 |
| Full doc family (FAQ/Assessment/admin/dev), Tiptap editor, Confluence/Notion | Phase 3 |
| Full Brand Kit (avatars, backgrounds, logos, glossary, pronunciations), voice cloning, BYO key | Phase 5 |
| Interactive demos | Phase 6 |
| Translation / multi-language | Phase 7 |
| Publish/share pages, analytics, Shared Pages | Phase 8 |
| Ask AI / RAG, Knowledge Base | Phase 9 |
| Skills presets, billing + AI-minute metering, **project memory (re-record + diff)** | Phase 10 |

> Note on uploads: in V1, plain uploads with **no** telemetry still generate a video, but auto-zoom is transcript/scene-based rather than click-precise. Click-precise zoom on plain uploads (CV) is V2. The extension/recorder path gets the full click-driven treatment.

---

## 2. Architecture (V1 — simplified)

Same spine as the full plan, minus multi-tenancy:

```
Capture (recorder | upload | extension)  → Capture Session
        ↓  FFmpeg · Whisper · telemetry merge
   Workflow Graph  (versioned JSON IR — the single source of truth)
        ↓
   Studio video generation (per-step TTS · buildTimeline · FFmpeg zoompan render)
        ↕  edit ↔ regenerate (targeted)
   Final MP4
```

- **No users/workspaces tables.** Top-level entity is a **project**.
- **Persistence:** SQLite (simplest for local V1); media on local filesystem (MinIO optional). No migrations ceremony.
- **Monorepo, trimmed:** `apps/web`, `apps/api`, `apps/workers`, `apps/extension`. No `player`, `desktop`, `k8s`, `ci`.
- **Workflow Graph and `buildTimeline` are unchanged and remain authoritative** — V2 features attach to them later without rework.

---

## 3. Lean phases (executable work orders)

Same execution loop as the master: read → restate plan + file list → build → run tests/verification → self-correct from logs → check exit criteria → stop. No gold-plating.

### V1-P0 — Lean foundation
*(replaces Phase 0; no auth/workspace/CI)*
- **E1** Trim monorepo: `web` (Next.js+TS+Tailwind+shadcn), `api` (FastAPI 3.12), `workers` (Celery+Redis), `extension` (MV3), `packages/workflow-graph` (IR schema+validator).
- **E2** Local persistence: SQLite + a tiny data layer; local media dir with read/write helpers (presigned-style interface so MinIO can drop in for V2).
- **E3** `make dev` runs web+api+worker locally; `.env.example`; `/healthz`.
- **Exit:** stack runs locally; IR validator passes on the master §2 example; a `project` can be created and read (no login).

### V1-P1 — Capture
*(subset of Phase 1: drop cloud imports, auth-tied ownership, Library UX)*
- **E1** In-app **recorder** (`getDisplayMedia`/`getUserMedia`, mic/system audio, countdown, pause/resume, timer) + parallel click log `{x,y,t}`.
- **E2** **Extension** (MV3): click/input(redacted)/navigation capture with selectors + bbox + `t_ms`; per-step screenshot; IndexedDB buffer; finish → upload → create session.
- **E3** **Upload**: drag-drop mp4/webm; ingest normalization; sessions with no telemetry flagged `telemetry=absent`.
- **E4** Minimal capture list (just enough to see sessions land).
- **Keep:** password/PII **masking at capture** (never record `type=password`). **Drop:** full PII redaction pass (no sharing in V1).
- **Exit:** recorder + extension produce media + aligned click log; upload creates a valid session; a 20-step flow captures cleanly.

### V1-P2 — AI understanding → Workflow Graph
*(core of Phase 2, trimmed)*
- **E1** FFmpeg frame extraction (scene-change + ~1fps cap) + audio demux + **Whisper word-level transcript** (RTX 5070 / CUDA 12.x — pin versions).
- **E2** **Merge + segment**: telemetry + transcript → steps at click boundaries (telemetry present); transcript/scene segmentation when `telemetry=absent`.
- **E3** **Claude extraction (LangGraph)**: label steps (action/target/intent/screen), write per-step `narration`, validate against IR schema, persist `workflow_graph v1`.
- **E4** Orchestration: enqueue on session complete; idempotent tasks keyed `(session, stage, version)`; retries + readable errors; progress to UI.
- **Drop for V1:** OCR-heavy screen naming (optional/light), CV click-detection fallback, full PII pass, cost ledger (keep a rough log).
- **Exit:** any session yields a schema-valid graph with click-segmented, narrated steps; pipeline is idempotent and retried; forced failure logs FFmpeg/Whisper stderr.

### V1-P3 — AI video generation, editor & the regenerate loop
*(Phase 4 spine + minimal Phase 5 voice; this is the release centerpiece)*
- **⚠️ E0 — Solve timeline drift first.** Segment narration by click → per-step TTS → build the output clock from per-step durations. `buildTimeline(clicks[], stepDurations[]) → segments[]` is pure and **exhaustively unit-tested** (no clicks / back-to-back / narration before first click / trailing narration / coord out of bounds / zero-duration step). Everything else depends on this.
- **E1 Minimal voice:** one `TTSProvider` (default OpenAI or ElevenLabs; local XTTS optional for offline dev). Per-step synthesis returning `{audio, duration_ms}`, cached by `(text_hash, voice_id)`. Speed control. (No cloning, no BYO key — V2.)
- **E2 Editor shell + Script panel:** tabs Script · Zooms · Scenes · Music · Captions (Avatar/Elements → V2). Timestamped editable script from the graph; **filler-word removal** (struck-through, re-flow); preview player.
- **E3 Zooms (telemetry-driven):** auto zoom marker per click at its segment start; editable/disable per marker.
- **E4 Scenes/captions/frame:** intro/outro, per-step scenes, add/reorder; captions from the TTS timeline; branded frame (rounded corners, gradient bg, browser mockup); aspect switch (16:9/9:16/1:1); background music with ducking.
- **E5 Render (FFmpeg-first):** per-segment `zoompan` at `(cx,cy)` + hold/trim to `d'[step]` → `concat` → mux per-step TTS → intro/outro + captions. Render on export only; preview client-side.
- **E6 — The regenerate loop (core requirement):**
  - *Initial generate:* graph → edit-spec → video.
  - *Regenerate from edits:* editing script text / toggling filler / nudging a zoom / reordering scenes marks only affected segments dirty and **re-synthesizes + re-renders only those**, preserving untouched segments and their edits. Cheap and fast.
- **Exit (release gate):** capture (record or extension) → AI-generated video → edit script/filler/zoom → **regenerate updates only changed segments** → export a drift-free MP4 with voiceover, click-zooms, captions, intro/outro on a real 2–3 min flow.

### V1-P4 — (Optional) Step-by-step doc + export
*Cheap off the same graph; cut freely if you want video-only V1.*
- **E1** Generate an SOP (numbered steps + best keyframe per step) from the graph.
- **E2** Export **Markdown + PDF** (no Tiptap editor, no Confluence/Notion — V2).
- **Exit:** one recording also yields a downloadable SOP.

---

## 4. Time & effort — V1 with Claude Code (Opus 4.8)

Unit = one experienced full-stack engineer *actively driving* Claude Code for a focused day (ed). Quality bar = the exit criteria above (tested spine, real end-to-end video), not a throwaway prototype.

| V1 phase | With Claude Code (ed) | Notes |
|---|---:|---|
| V1-P0 Lean foundation | 2 | No auth/workspace/CI strips most of it |
| V1-P1 Capture | 7 | MV3 buffering + recorder are the real work |
| V1-P2 Understanding | 13 | Whisper/FFmpeg env tuning dominates wall-clock |
| V1-P3 Video + voice + regenerate | 18 | `buildTimeline` + render + regen loop; the centerpiece |
| V1-P4 Doc + export (optional) | 4 | Nearly free off the graph |
| **Total (video-only)** | **~40 ed** | |
| **Total (with doc)** | **~44 ed** | |

**Calendar (video-only ~40 ed, incl. +25% contingency):**

| Team | To first end-to-end demo (record→generated video) | To V1 release |
|---|---|---|
| Solo + Claude Code | ~3–4 weeks | **~9–11 weeks (~2–2.5 months)** |
| **2 engineers + Claude Code** | ~2–3 weeks | **~6–7 weeks (~1.5 months)** |

Critical path is serial-ish: P0 → P1 → P2 → P3. With two engineers, overlap the extension/recorder (P1) and pipeline plumbing (P2) while the editor UI (P3 frontend) is built against a mocked graph, then integrate. A third engineer adds little here — the dependency chain, not Claude Code, is the limiter.

**Where Claude Code flies (2.5–4×):** scaffolding, the editor UI, TTS adapter, FFmpeg command generation, test generation.
**Where it doesn't (1.3–1.6×) — don't rush these:** Whisper/CUDA env on the RTX 5070, FFmpeg filtergraph tuning, and *verifying* `buildTimeline` + the regenerate-diff edge cases (Claude writes them in minutes; correctness review is human time).

---

## 5. V1 exit criteria (release checklist)

- [ ] Capture works from recorder, extension, and upload (no login anywhere).
- [ ] Any session produces a schema-valid Workflow Graph.
- [ ] `buildTimeline` passes its full edge-case suite.
- [ ] Initial AI video generates with voiceover, click-driven zooms, captions, intro/outro — no audio/video drift at 3:00.
- [ ] Editing script/filler/zoom and hitting regenerate updates **only** changed segments and preserves the rest.
- [ ] Export a final MP4 (and, if P4 built, an SOP MD/PDF).
- [ ] `PROGRESS.md` shows V1-P0..P3 (and P4 if built) ticked.

## 6. Handoff to V2
V2 re-attaches to the same graph + `buildTimeline`: auth/workspaces, sharing + analytics, translation, interactive demos, Ask AI/KB, full Brand Kit, Skills, billing, and **project memory** (re-record + diff). Use the original `PHASE-*` files as their work orders — nothing built in V1 needs to be redone, only extended.
