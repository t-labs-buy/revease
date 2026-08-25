// Background service worker: owns capture state, buffers events/screenshots to
// IndexedDB, and on finish uploads everything as a Refract `extension` session.
// State lives in chrome.storage.session so a suspended worker resumes cleanly.

import { clearAll, getAll, putEvent, putScreenshot } from "./idb.js";
import {
  DEFAULT_API_BASE,
  completeSession,
  createSession,
  postEvents,
  registerAndUpload,
} from "./api.js";
import { abortRun, getStatus, pauseRun, resumeRun, startRun } from "./agent.js";

const SHOT_MIN_INTERVAL_MS = 1100; // captureVisibleTab is rate-limited; coalesce.

async function state() {
  const s = await chrome.storage.session.get(["recording", "startTs", "seq", "lastShotTs"]);
  return { recording: false, startTs: 0, seq: 0, lastShotTs: 0, ...s };
}

async function setState(patch) {
  await chrome.storage.session.set(patch);
}

async function broadcast(recording) {
  const tabs = await chrome.tabs.query({});
  for (const t of tabs) {
    if (t.id != null) chrome.tabs.sendMessage(t.id, { kind: "state", recording }).catch(() => {});
  }
}

async function startCapture() {
  await clearAll();
  await setState({ recording: true, startTs: Date.now(), seq: 0, lastShotTs: 0 });
  await broadcast(true);
}

async function maybeScreenshot(seq) {
  const s = await state();
  const now = Date.now();
  if (now - s.lastShotTs < SHOT_MIN_INTERVAL_MS) return; // throttle
  await setState({ lastShotTs: now });
  try {
    const dataUrl = await chrome.tabs.captureVisibleTab({ format: "png" });
    if (dataUrl) await putScreenshot(seq, dataUrl);
  } catch {
    /* rate-limited or restricted page — log-and-continue */
  }
}

async function recordEvent(evt, wantShot) {
  const s = await state();
  if (!s.recording) return;
  const seq = s.seq;
  await setState({ seq: seq + 1 });
  await putEvent({
    seq,
    type: evt.type,
    t_ms: Math.max(0, Date.now() - s.startTs),
    selector: evt.selector ?? null,
    text: evt.text ?? null,
    bbox: evt.bbox ?? null,
    value_redacted: evt.value_redacted ?? null,
  });
  if (wantShot) await maybeScreenshot(seq);
}

async function dataUrlToBlob(dataUrl) {
  const res = await fetch(dataUrl);
  return res.blob();
}

async function finishCapture() {
  const s = await state();
  await setState({ recording: false });
  await broadcast(false);

  const cfg = await chrome.storage.local.get(["apiBase", "projectId"]);
  const apiBase = cfg.apiBase || DEFAULT_API_BASE;
  const projectId = cfg.projectId;
  if (!projectId) throw new Error("No project selected");

  const events = (await getAll("events")).sort((a, b) => a.seq - b.seq);
  const shots = await getAll("screenshots");
  const durationMs = events.length ? events[events.length - 1].t_ms : 0;

  const session = await createSession(apiBase, projectId, { w: 1280, h: 720 });
  for (const shot of shots) {
    const blob = await dataUrlToBlob(shot.dataUrl);
    await registerAndUpload(apiBase, session.id, "screenshot", "png", blob, { seq: shot.seq });
  }
  await postEvents(
    apiBase,
    session.id,
    events.map((e) => ({
      seq: e.seq,
      type: e.type,
      t_ms: e.t_ms,
      selector: e.selector,
      text: e.text,
      bbox: e.bbox,
      value_redacted: e.value_redacted,
    })),
  );
  const done = await completeSession(apiBase, session.id, durationMs);
  await clearAll();
  return { sessionId: session.id, events: events.length, screenshots: shots.length, telemetry: done.telemetry };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  // Messages addressed to the offscreen doc / agent controller are handled by
  // their own listeners (agent.js, offscreen.js) — don't double-handle here.
  if (msg && msg.target) return false;
  if (msg && msg.kind === "auto-status") return false; // agent->sidepanel broadcast
  (async () => {
    try {
      if (msg.kind === "event") {
        await recordEvent(msg.event, msg.wantShot);
        sendResponse({ ok: true });
      } else if (msg.kind === "queryState") {
        const s = await state();
        sendResponse({ recording: s.recording });
      } else if (msg.kind === "start") {
        await startCapture();
        sendResponse({ ok: true });
      } else if (msg.kind === "stop") {
        const result = await finishCapture();
        sendResponse({ ok: true, result });
      } else if (msg.kind === "auto-start") {
        const r = await startRun(msg.config);
        sendResponse({ ok: true, result: r });
      } else if (msg.kind === "auto-pause") {
        pauseRun();
        sendResponse({ ok: true });
      } else if (msg.kind === "auto-resume") {
        resumeRun();
        sendResponse({ ok: true });
      } else if (msg.kind === "auto-abort") {
        abortRun();
        sendResponse({ ok: true });
      } else if (msg.kind === "auto-query") {
        sendResponse({ ok: true, status: getStatus() });
      } else {
        sendResponse({ ok: false, error: "unknown message" });
      }
    } catch (e) {
      sendResponse({ ok: false, error: String(e) });
    }
  })();
  return true; // async response
});
