// Auto Record controller: owns one AI-driven run end to end. Creates the run +
// session on the API, records the chosen tab (offscreen doc), then loops
// observe -> POST /step -> execute via CDP -> log telemetry, until the agent says
// done (or a cap/abort). Finalizes by uploading the recording + events and handing
// the session to the ordinary understanding pipeline.

import { completeAgentRun, createAgentRun, postAgentStep, postEvents, registerAndUpload } from "./api.js";
import { attach, detach, execute, observe, screenshot } from "./driver.js";
import { clearAll, getAll, putEvent, putScreenshot } from "./idb.js";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const MAX_WALL_MS = 10 * 60 * 1000;
const MAX_CONSEC_FAILS = 3;
const RESTRICTED = ["chrome://", "chrome-extension://", "edge://", "about:", "https://chromewebstore.google.com", "https://chrome.google.com/webstore"];

// Single active run (single-user V1). Mutated by the message handlers below.
let run = null;

function isRestricted(url) {
  return !url || RESTRICTED.some((p) => url.startsWith(p));
}

function status(patch) {
  if (run) Object.assign(run.status, patch);
  chrome.runtime.sendMessage({ kind: "auto-status", status: run ? run.status : { phase: "idle" } }).catch(() => {});
}

function log(line) {
  if (!run) return;
  run.status.log = [...(run.status.log || []).slice(-60), line];
  status({});
}

// ---- offscreen recorder plumbing ----
let _recStarted = null;
let _recUploaded = null;

chrome.runtime.onMessage.addListener((msg) => {
  if (!msg || msg.target !== "background") return;
  if (msg.kind === "recorder-started" && _recStarted) _recStarted();
  if (msg.kind === "recorder-uploaded" && _recUploaded) _recUploaded(msg);
});

async function ensureOffscreen() {
  const has = chrome.offscreen.hasDocument ? await chrome.offscreen.hasDocument() : false;
  if (!has) {
    await chrome.offscreen.createDocument({
      url: "src/offscreen.html",
      reasons: ["USER_MEDIA"],
      justification: "Record the selected tab for an Auto Record demo video.",
    });
  }
}

async function startRecording(tabId, apiBase, sessionId) {
  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });
  await ensureOffscreen();
  const started = new Promise((res) => (_recStarted = res));
  await chrome.runtime.sendMessage({ target: "offscreen", kind: "offscreen-start", streamId, apiBase, sessionId });
  await Promise.race([started, sleep(8000)]);
  _recStarted = null;
}

async function stopRecording() {
  const uploaded = new Promise((res) => (_recUploaded = res));
  await chrome.runtime.sendMessage({ target: "offscreen", kind: "offscreen-stop" });
  const result = await Promise.race([uploaded, sleep(30000)]);
  _recUploaded = null;
  await chrome.offscreen.closeDocument().catch(() => {});
  return result || {};
}

// ---- lifecycle ----
export async function startRun({ apiBase, projectId, coveragePlan, transcript, startUrl, maxSteps }) {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  if (!tab || tab.id == null) throw new Error("no active tab to record");
  if (isRestricted(tab.url)) throw new Error("cannot record this page (browser/system page). Open your product tab first.");

  const created = await createAgentRun(apiBase, {
    project_id: projectId,
    coverage_plan: coveragePlan,
    transcript: transcript || "",
    start_url: startUrl || null,
    max_steps: maxSteps || 60,
    viewport: { w: 1280, h: 720 },
  });

  run = {
    apiBase, tabId: tab.id, runId: created.run_id, sessionId: created.session_id,
    paused: false, aborted: false, startTs: 0, stepIndex: 0, consecFails: 0,
    status: { phase: "starting", runId: created.run_id, sessionId: created.session_id, projectId, step: 0, plan: created.plan, log: [] },
  };
  status({});
  await clearAll();

  // Attach the debugger BEFORE recording so the (possible) infobar viewport resize
  // settles and telemetry bboxes match the recorded frames. onDetach = user cancel.
  chrome.debugger.onDetach.addListener(_onDetach);
  await attach(tab.id);
  await sleep(500);

  if (startUrl) {
    try { await chrome.tabs.update(tab.id, { url: startUrl }); await sleep(1500); } catch { /* ignore */ }
  }

  status({ phase: "recording" });
  await startRecording(tab.id, apiBase, created.session_id);
  run.startTs = Date.now();
  status({ phase: "driving" });

  _loop().catch((e) => { log("loop error: " + e); void finalize("failed"); });
  return { runId: run.runId, sessionId: run.sessionId };
}

function _onDetach(source) {
  if (run && source && source.tabId === run.tabId && run.status.phase === "driving") {
    log("debugger detached (banner cancelled?) — salvaging recording");
    run.aborted = true;
    void finalize(run.stepIndex > 0 ? "completed" : "aborted");
  }
}

export function pauseRun() { if (run) { run.paused = true; status({ phase: "paused" }); } }
export function resumeRun() { if (run) { run.paused = false; status({ phase: "driving" }); } }
export function abortRun() { if (run && !run.aborted) { run.aborted = true; log("aborted by user"); } }
export function getStatus() { return run ? run.status : { phase: "idle" }; }

async function _loop() {
  let elements = [];
  let lastResults = [];
  while (run && !run.aborted) {
    if (Date.now() - run.startTs > MAX_WALL_MS) { log("reached 10-minute limit"); break; }
    if (run.paused) { await sleep(400); continue; }

    const obs = await observe(run.tabId);
    elements = obs.elements || [];

    let resp;
    try {
      resp = await _stepWithRetry({ expected_index: run.stepIndex, observation: obs, results: lastResults });
    } catch (e) {
      log("decision failed: " + e);
      break;
    }
    lastResults = [];
    run.stepIndex = resp.step_count;
    run.status.step = resp.step_count;
    run.status.plan = resp.plan;
    if (resp.progress_note) log(resp.progress_note);
    status({});

    if (resp.done) { log("agent finished the plan"); return void finalize("completed"); }

    const action = resp.action;
    await sleep(action.action === "navigate" ? 150 : 600); // settle so the video is watchable
    const r = await execute(run.tabId, action, elements, run.startTs);

    if (r.event) {
      await putEvent({
        seq: action.index, type: r.event.type, t_ms: r.event.t_ms,
        selector: r.event.selector ?? null, text: r.event.text ?? null,
        bbox: r.event.bbox ?? null, value_redacted: r.event.value_redacted ?? null,
      });
      const shot = await screenshot(run.tabId);
      if (shot) await putScreenshot(action.index, "data:image/jpeg;base64," + shot);
    }
    lastResults.push({
      index: action.index, ok: r.ok, error: r.error || null,
      selector: r.event ? r.event.selector : null, bbox: r.event ? r.event.bbox : null,
      t_ms: r.event ? r.event.t_ms : null,
    });
    run.consecFails = r.ok ? 0 : run.consecFails + 1;
    if (run.consecFails >= MAX_CONSEC_FAILS) { log("too many consecutive failures — stopping"); break; }
    if (r.error) log("⚠ " + r.error);
  }
  await finalize(run && run.aborted ? "aborted" : "completed");
}

async function _stepWithRetry(body) {
  try {
    return await postAgentStep(run.apiBase, run.runId, body);
  } catch (e) {
    await sleep(800); // network blip: server may have already advanced -> idempotent replay
    return await postAgentStep(run.apiBase, run.runId, body);
  }
}

let _finalizing = false;
async function finalize(status_) {
  if (!run || _finalizing) return;
  _finalizing = true;
  const r = run;
  chrome.debugger.onDetach.removeListener(_onDetach);
  r.status.phase = "uploading";
  status({});

  const durationMs = r.startTs ? Date.now() - r.startTs : 0;
  try { await stopRecording(); } catch (e) { log("recorder stop failed: " + e); }
  if (!r.aborted || status_ === "completed") {
    try {
      const events = (await getAll("events")).sort((a, b) => a.seq - b.seq);
      const shots = await getAll("screenshots");
      for (const s of shots) {
        const blob = await (await fetch(s.dataUrl)).blob();
        await registerAndUpload(r.apiBase, r.sessionId, "screenshot", "jpg", blob, { seq: s.seq });
      }
      await postEvents(r.apiBase, r.sessionId, events.map((e) => ({
        seq: e.seq, type: e.type, t_ms: e.t_ms, selector: e.selector,
        text: e.text, bbox: e.bbox, value_redacted: e.value_redacted,
      })));
    } catch (e) {
      log("upload failed: " + e);
    }
  }
  try { await completeAgentRun(r.apiBase, r.runId, status_, durationMs); } catch (e) { log("complete failed: " + e); }
  try { await detach(r.tabId); } catch { /* ignore */ }
  await clearAll();
  r.status.phase = status_ === "completed" ? "done" : status_;
  status({});
  run = null;
  _finalizing = false;
}
