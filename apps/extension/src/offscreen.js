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

// Same limits as the web app (500 MB / 30 min per recording): stop the encoder
// just under them and keep what was recorded; the run's later steps are simply
// not on video. Keeps an Auto Record run from producing an upload the server
// refuses.
const STOP_BYTES = (500 - 12) * 1024 * 1024;
const STOP_MS = 30 * 60 * 1000 - 2000;
let bytes = 0;
let startedAt = 0;
let limitHit = null; // "size" | "time" | null
let limitTimer = null;

function capRecording(reason) {
  if (limitHit || !recorder || recorder.state === "inactive") return;
  limitHit = reason;
  recorder.stop();
  chrome.runtime.sendMessage({ target: "background", kind: "recorder-limit", reason });
}

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
  bytes = 0;
  limitHit = null;
  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size) {
      chunks.push(e.data);
      bytes += e.data.size;
      if (bytes >= STOP_BYTES) capRecording("size");
    }
  };
  recorder.onstart = () => {
    // Clock zero for all telemetry — measured from the actual encoder start.
    chrome.runtime.sendMessage({ target: "background", kind: "recorder-started" });
  };
  recorder.start(1000); // 1s timeslice so a crash still leaves recoverable data
  startedAt = Date.now();
  limitTimer = setInterval(() => {
    if (Date.now() - startedAt >= STOP_MS) capRecording("time");
  }, 1000);
}

async function stop() {
  if (!recorder) return;
  clearInterval(limitTimer);
  if (recorder.state !== "inactive") {
    const done = new Promise((resolve) => (recorder.onstop = resolve));
    recorder.stop();
    await done;
  } else {
    await new Promise((r) => setTimeout(r, 300)); // let the final dataavailable land
  }
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
    limit: limitHit,
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
