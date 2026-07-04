# Refract Capture Extension (MV3)

Manifest V3 extension. Captures click / input(redacted) / navigation events with selectors,
bounding boxes and `t_ms`, plus per-step screenshots (throttled to respect `captureVisibleTab`
limits), buffers everything to IndexedDB (survives service-worker suspension), and on finish
uploads + creates a `capture_session` (`source_type=extension`). Password fields are never
captured. It emits the **same** event/session shape as the in-app recorder, so the Phase 2
pipeline does not care which source produced a session.

## Files
- `manifest.json` — MV3 manifest (background SW + content script + popup)
- `src/content.js` — DOM event capture (click/input/navigation), selector + bbox + label
- `src/background.js` — capture state, IndexedDB buffering, screenshot, upload on finish
- `src/idb.js` — IndexedDB event/screenshot buffer
- `src/api.js` — Refract backend client (same endpoints the web app uses)
- `src/popup.html` / `src/popup.js` — Start/Stop UI + project picker

## Load & use (dev)
1. Start the backend: `make dev` (API at `http://localhost:8000`), create a project in the web app.
2. Chrome → `chrome://extensions` → enable **Developer mode** → **Load unpacked** → select this
   `apps/extension` folder.
3. Click the Refract icon → pick your project → **Start** → click through a flow on any site →
   **Stop & upload**. The session appears under the project in the web app.
