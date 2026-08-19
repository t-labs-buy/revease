// Offscreen document: resolves a tabCapture media-stream id into a MediaRecorder
// and records the chosen tab to a WebM blob. Runs here (not the service worker or
// popup) because only a real document has MediaRecorder and can outlive focus
// changes / worker suspension. On stop it uploads the blob straight to the API —
// offscreen docs can fetch, so the (large) blob never crosses the messaging boundary.

import { registerAndUpload } from "./api.js";

let recorder = null;
let chunks = [];
let stream = null;
let ctx = null; // recording context: { apiBase, sessionId }

function pickMime() {
  const cands = [
    "video/webm;codecs=vp9",
    "video/webm;codecs=vp8",
    "video/webm",
    "video/mp4",
  ];
  for (const m of cands) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

async function start({ streamId, apiBase, sessionId }) {
  ctx = { apiBase, sessionId };
  chunks = [];
  stream = await navigator.mediaDevices.getUserMedia({
    audio: false, // narration is TTS'd from the transcript later; video only
    video: {
      mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: streamId },
    },
  });
  const mimeType = pickMime();
  recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size) chunks.push(e.data);
  };
  recorder.onstart = () => {
    // Clock zero for all telemetry — measured from the actual encoder start.
    chrome.runtime.sendMessage({ target: "background", kind: "recorder-started" });
  };
  recorder.start(1000); // 1s timeslice so a crash still leaves recoverable data
}

async function stop() {
  if (!recorder) return;
  const done = new Promise((resolve) => (recorder.onstop = resolve));
  recorder.stop();
  await done;
  for (const t of stream ? stream.getTracks() : []) t.stop();

  const type = recorder.mimeType || "video/webm";
  const blob = new Blob(chunks, { type });
  let storageKey = null;
  let error = null;
  try {
    storageKey = await registerAndUpload(ctx.apiBase, ctx.sessionId, "raw_video", "webm", blob);
  } catch (e) {
    error = String(e);
  }
  recorder = null;
  stream = null;
  chunks = [];
  chrome.runtime.sendMessage({
    target: "background",
    kind: "recorder-uploaded",
    storageKey,
    bytes: blob.size,
    error,
  });
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || msg.target !== "offscreen") return; // not for us
  (async () => {
    try {
      if (msg.kind === "offscreen-start") {
        await start(msg);
        sendResponse({ ok: true });
      } else if (msg.kind === "offscreen-stop") {
        await stop();
        sendResponse({ ok: true });
      } else {
        sendResponse({ ok: false, error: "unknown offscreen message" });
      }
    } catch (e) {
      sendResponse({ ok: false, error: String(e) });
    }
  })();
  return true;
});
