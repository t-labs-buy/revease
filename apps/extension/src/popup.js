import { listProjects } from "./api.js";

const $ = (id) => document.getElementById(id);
const apiBaseEl = $("apiBase");
const tokenEl = $("token");
const projectEl = $("project");
const startEl = $("start");
const stopEl = $("stop");
const statusEl = $("status");

function setStatus(msg, isErr) {
  statusEl.textContent = msg;
  statusEl.className = isErr ? "err" : "";
}

function send(msg) {
  return new Promise((resolve) => chrome.runtime.sendMessage(msg, resolve));
}

async function loadProjects() {
  try {
    const projects = await listProjects(apiBaseEl.value);
    projectEl.innerHTML = "";
    for (const p of projects) {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name;
      projectEl.appendChild(opt);
    }
    const cfg = await chrome.storage.local.get("projectId");
    if (cfg.projectId) projectEl.value = cfg.projectId;
    if (!projects.length) setStatus("No projects — create one in the web app first.", true);
  } catch (e) {
    setStatus(`Cannot reach API: ${e}`, true);
  }
}

async function refreshRecordingUI() {
  const res = await send({ kind: "queryState" });
  const recording = !!(res && res.recording);
  startEl.disabled = recording;
  stopEl.disabled = !recording;
  if (recording) setStatus("● Recording…");
}

apiBaseEl.addEventListener("change", async () => {
  await chrome.storage.local.set({ apiBase: apiBaseEl.value });
  await loadProjects();
});
// The token is what makes every request work, so re-list projects on change to
// give immediate feedback on whether it was accepted.
tokenEl.addEventListener("change", async () => {
  await chrome.storage.local.set({ accessToken: tokenEl.value.trim() });
  await loadProjects();
});
projectEl.addEventListener("change", () =>
  chrome.storage.local.set({ projectId: projectEl.value }),
);

startEl.addEventListener("click", async () => {
  await chrome.storage.local.set({ apiBase: apiBaseEl.value, projectId: projectEl.value });
  const res = await send({ kind: "start" });
  if (res && res.ok) {
    setStatus("● Recording… navigate & click, then Stop.");
    startEl.disabled = true;
    stopEl.disabled = false;
  } else {
    setStatus(`Start failed: ${res && res.error}`, true);
  }
});

stopEl.addEventListener("click", async () => {
  setStatus("Uploading…");
  stopEl.disabled = true;
  const res = await send({ kind: "stop" });
  if (res && res.ok) {
    const r = res.result;
    setStatus(`Saved: ${r.events} events, ${r.screenshots} shots (telemetry ${r.telemetry}).`);
    startEl.disabled = false;
  } else {
    setStatus(`Stop failed: ${res && res.error}`, true);
    startEl.disabled = false;
  }
});

$("autorec").addEventListener("click", async () => {
  // Open the persistent side panel (the popup dies on focus change; a multi-minute
  // AI-driven run needs a surface that survives switching to the recorded tab).
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  try {
    if (tab && tab.windowId != null) await chrome.sidePanel.open({ windowId: tab.windowId });
    window.close();
  } catch (e) {
    setStatus(`Could not open side panel: ${e}`, true);
  }
});

(async () => {
  const cfg = await chrome.storage.local.get(["apiBase", "accessToken"]);
  if (cfg.apiBase) apiBaseEl.value = cfg.apiBase;
  if (cfg.accessToken) tokenEl.value = cfg.accessToken;
  await loadProjects();
  await refreshRecordingUI();
})();
