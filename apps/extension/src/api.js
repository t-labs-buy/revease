// Thin API client for the Refract backend (same endpoints the web app uses).
//
// Every endpoint below is private, so each request carries the access token the
// user pasted into the side panel (stored in chrome.storage.local as
// `accessToken`, alongside `apiBase`). The token is read here rather than being
// threaded through every caller, so background.js / agent.js / offscreen.js don't
// need to know about auth at all.

async function accessToken() {
  const { accessToken } = await chrome.storage.local.get("accessToken");
  return accessToken || "";
}

/** Headers for a JSON request, with the bearer token when we have one. */
async function jsonHeaders() {
  const token = await accessToken();
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

/** Headers for a raw body (media upload) — no Content-Type override. */
async function authHeaders() {
  const token = await accessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Turn a failed response into an error, with a pointed message on 401/403 so
 *  the user knows to reconnect rather than hunting a generic status code. */
async function fail(what, response) {
  if (response.status === 401 || response.status === 403) {
    throw new Error(
      `${what}: not signed in. Open the RevEase side panel and paste a fresh ` +
        `access token from the web app (Account → Connect extension).`,
    );
  }
  throw new Error(`${what} ${response.status}`);
}

export async function createSession(apiBase, projectId, viewport) {
  const r = await fetch(`${apiBase}/sessions`, {
    method: "POST",
    headers: await jsonHeaders(),
    body: JSON.stringify({ project_id: projectId, source_type: "extension", viewport }),
  });
  if (!r.ok) await fail("createSession", r);
  return r.json();
}

export async function registerAndUpload(apiBase, sessionId, kind, ext, blob, meta) {
  const reg = await fetch(`${apiBase}/sessions/${sessionId}/assets`, {
    method: "POST",
    headers: await jsonHeaders(),
    body: JSON.stringify({ kind, ext, meta }),
  });
  if (!reg.ok) await fail("registerAsset", reg);
  const target = await reg.json();
  const put = await fetch(`${apiBase}${target.url}`, {
    method: "PUT",
    headers: await authHeaders(),
    body: blob,
  });
  if (!put.ok) await fail("upload", put);
  return target.storage_key;
}

export async function postEvents(apiBase, sessionId, events) {
  if (!events.length) return;
  const r = await fetch(`${apiBase}/sessions/${sessionId}/events`, {
    method: "POST",
    headers: await jsonHeaders(),
    body: JSON.stringify({ events }),
  });
  if (!r.ok) await fail("postEvents", r);
}

export async function completeSession(apiBase, sessionId, durationMs) {
  const r = await fetch(`${apiBase}/sessions/${sessionId}/complete`, {
    method: "POST",
    headers: await jsonHeaders(),
    body: JSON.stringify({ duration_ms: durationMs ?? null }),
  });
  if (!r.ok) await fail("completeSession", r);
  return r.json();
}

export async function listProjects(apiBase) {
  const r = await fetch(`${apiBase}/projects`, { headers: await authHeaders() });
  if (!r.ok) await fail("listProjects", r);
  return r.json();
}

// ---- Auto Record (AI-driven) ----

export async function createAgentRun(apiBase, body) {
  const r = await fetch(`${apiBase}/auto-record/runs`, {
    method: "POST",
    headers: await jsonHeaders(),
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`createAgentRun ${r.status}: ${await r.text()}`);
  return r.json();
}

export async function postAgentStep(apiBase, runId, body) {
  const r = await fetch(`${apiBase}/auto-record/runs/${runId}/step`, {
    method: "POST",
    headers: await jsonHeaders(),
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`postAgentStep ${r.status}: ${await r.text()}`);
  return r.json();
}

export async function completeAgentRun(apiBase, runId, status, durationMs) {
  const r = await fetch(`${apiBase}/auto-record/runs/${runId}/complete`, {
    method: "POST",
    headers: await jsonHeaders(),
    body: JSON.stringify({ status, duration_ms: durationMs ?? null }),
  });
  if (!r.ok) await fail("completeAgentRun", r);
  return r.json();
}
