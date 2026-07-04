// Thin API client for the Refract backend (same endpoints the web app uses).

export async function createSession(apiBase, projectId, viewport) {
  const r = await fetch(`${apiBase}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, source_type: "extension", viewport }),
  });
  if (!r.ok) throw new Error(`createSession ${r.status}`);
  return r.json();
}

export async function registerAndUpload(apiBase, sessionId, kind, ext, blob, meta) {
  const reg = await fetch(`${apiBase}/sessions/${sessionId}/assets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, ext, meta }),
  });
  if (!reg.ok) throw new Error(`registerAsset ${reg.status}`);
  const target = await reg.json();
  const put = await fetch(`${apiBase}${target.url}`, { method: "PUT", body: blob });
  if (!put.ok) throw new Error(`upload ${put.status}`);
  return target.storage_key;
}

export async function postEvents(apiBase, sessionId, events) {
  if (!events.length) return;
  const r = await fetch(`${apiBase}/sessions/${sessionId}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ events }),
  });
  if (!r.ok) throw new Error(`postEvents ${r.status}`);
}

export async function completeSession(apiBase, sessionId, durationMs) {
  const r = await fetch(`${apiBase}/sessions/${sessionId}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ duration_ms: durationMs ?? null }),
  });
  if (!r.ok) throw new Error(`completeSession ${r.status}`);
  return r.json();
}

export async function listProjects(apiBase) {
  const r = await fetch(`${apiBase}/projects`);
  if (!r.ok) throw new Error(`listProjects ${r.status}`);
  return r.json();
}
