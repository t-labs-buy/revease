import { listProjects } from "./api.js";

const $ = (id) => document.getElementById(id);
const els = {
  apiBase: $("apiBase"), project: $("project"), startUrl: $("startUrl"),
  plan: $("plan"), transcript: $("transcript"), start: $("start"),
  form: $("form"), live: $("live"), timer: $("timer"), step: $("step"),
  phase: $("phase"), planList: $("plan"), pause: $("pause"), abort: $("abort"),
  status: $("status"), logbox: $("logbox"),
};

let paused = false;
let startedAt = 0;
let timerId = null;

function setStatus(msg, isErr) {
  els.status.textContent = msg || "";
  els.status.className = isErr ? "err" : "";
}

function send(msg) {
  return new Promise((resolve) => chrome.runtime.sendMessage(msg, resolve));
}

async function loadProjects() {
  try {
    const projects = await listProjects(els.apiBase.value);
    els.project.innerHTML = "";
    for (const p of projects) {
      const o = document.createElement("option");
      o.value = p.id; o.textContent = p.name;
      els.project.appendChild(o);
    }
    const cfg = await chrome.storage.local.get("projectId");
    if (cfg.projectId) els.project.value = cfg.projectId;
    if (!projects.length) setStatus("No projects — create one in the web app first.", true);
    else setStatus("");
  } catch (e) {
    setStatus(`Cannot reach API: ${e}`, true);
  }
}

function fmt(ms) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function showLive(on) {
  els.form.classList.toggle("hidden", on);
  els.live.classList.toggle("hidden", !on);
  els.start.disabled = on;
}

function renderStatus(st) {
  if (!st) return;
  els.phase.textContent = st.phase || "";
  els.step.textContent = st.step ?? 0;
  if (Array.isArray(st.plan)) {
    els.planList.innerHTML = "";
    for (const it of st.plan) {
      const li = document.createElement("li");
      li.textContent = (it.status === "done" ? "✓ " : "• ") + it.text;
      li.className = it.status;
      els.planList.appendChild(li);
    }
  }
  if (Array.isArray(st.log)) {
    els.logbox.innerHTML = "";
    for (const line of st.log.slice(-40)) {
      const d = document.createElement("div");
      d.textContent = line;
      els.logbox.appendChild(d);
    }
    els.logbox.scrollTop = els.logbox.scrollHeight;
  }
  if (["done", "aborted", "failed"].includes(st.phase)) {
    stopTimer();
    showLive(false);
    setStatus(st.phase === "done"
      ? "Done — processing started. Open the project in the web app to edit & render."
      : `Run ${st.phase}.`, st.phase !== "done");
  }
}

function startTimer() {
  startedAt = Date.now();
  timerId = setInterval(() => (els.timer.textContent = fmt(Date.now() - startedAt)), 500);
}
function stopTimer() { if (timerId) clearInterval(timerId); timerId = null; }

els.apiBase.addEventListener("change", async () => {
  await chrome.storage.local.set({ apiBase: els.apiBase.value });
  await loadProjects();
});
els.project.addEventListener("change", () =>
  chrome.storage.local.set({ projectId: els.project.value }));

els.start.addEventListener("click", async () => {
  if (!els.plan.value.trim()) return setStatus("Add at least one coverage-plan item.", true);
  await chrome.storage.local.set({ apiBase: els.apiBase.value, projectId: els.project.value });
  setStatus("Starting…");
  const res = await send({
    kind: "auto-start",
    config: {
      apiBase: els.apiBase.value,
      projectId: els.project.value,
      coveragePlan: els.plan.value,
      transcript: els.transcript.value,
      startUrl: els.startUrl.value.trim() || null,
      maxSteps: 60,
    },
  });
  if (res && res.ok) {
    showLive(true);
    startTimer();
    setStatus("");
  } else {
    setStatus(`Start failed: ${res && res.error}`, true);
  }
});

els.pause.addEventListener("click", async () => {
  paused = !paused;
  await send({ kind: paused ? "auto-pause" : "auto-resume" });
  els.pause.textContent = paused ? "Resume" : "Pause";
});

els.abort.addEventListener("click", async () => {
  els.abort.disabled = true;
  await send({ kind: "auto-abort" });
  setStatus("Stopping & uploading…");
});

// Live updates pushed by the agent controller.
chrome.runtime.onMessage.addListener((msg) => {
  if (msg && msg.kind === "auto-status") renderStatus(msg.status);
});

(async () => {
  const cfg = await chrome.storage.local.get("apiBase");
  if (cfg.apiBase) els.apiBase.value = cfg.apiBase;
  await loadProjects();
  // If a run is already in progress (panel reopened), resume the live view.
  const res = await send({ kind: "auto-query" });
  if (res && res.status && !["idle", "done", "aborted", "failed"].includes(res.status.phase)) {
    showLive(true);
    startTimer();
    renderStatus(res.status);
  }
})();
