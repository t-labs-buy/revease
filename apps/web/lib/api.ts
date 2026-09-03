import { API_BASE, absoluteApiBase, apiFetch } from "@/lib/http";

// Re-exported so callers that build media/asset URLs keep importing it from here.
export { API_BASE, absoluteApiBase };

export interface Project {
  id: string;
  name: string;
  favorite?: number; // 0/1 — starred projects sort first
  created_at: string;
  has_document?: boolean; // a step-by-step doc has actually been generated
  capture_count?: number; // how many recordings/uploads this project holds
  // Set only for admins browsing all spaces, and only on other users' projects.
  owner_email?: string | null;
  owner_name?: string | null;
}

/** "mine" (default) = the caller's own space; "all" = every user's space.
 *  The API honours "all" only for admins and silently ignores it otherwise. */
export type ListScope = "mine" | "all";

export async function setKeepRanges(sessionId: string, ranges: number[][]): Promise<void> {
  const r = await apiFetch(`/sessions/${sessionId}/keep-ranges`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ranges }),
  });
  if (!r.ok) throw new Error(`setKeepRanges failed: ${r.status}`);
}

export async function deleteProject(projectId: string): Promise<void> {
  const r = await apiFetch(`/projects/${projectId}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`deleteProject failed: ${r.status}`);
}

export async function toggleFavorite(projectId: string): Promise<Project> {
  const r = await apiFetch(`/projects/${projectId}/favorite`, { method: "POST" });
  if (!r.ok) throw new Error(`toggleFavorite failed: ${r.status}`);
  return r.json();
}

export async function listProjects(scope: ListScope = "mine"): Promise<Project[]> {
  const r = await apiFetch(`/projects?scope=${scope}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listProjects failed: ${r.status}`);
  return r.json();
}

export async function getProject(id: string): Promise<Project> {
  const r = await apiFetch(`/projects/${id}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getProject failed: ${r.status}`);
  return r.json();
}

export async function createProject(name: string): Promise<Project> {
  const r = await apiFetch(`/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!r.ok) throw new Error(`createProject failed: ${r.status}`);
  return r.json();
}

// ---- capture sessions ----
export type SourceType = "extension" | "recorder" | "upload";
export type EventType = "click" | "input" | "navigation" | "scroll" | "keydown";

export interface Session {
  id: string;
  project_id: string;
  source_type: string;
  telemetry: string;
  status: string;
  duration_ms: number | null;
  trim_start_ms?: number | null;
  trim_end_ms?: number | null;
  poster?: string | null;
  created_at: string;
}

export interface Asset {
  id: string;
  kind: string;
  storage_key: string;
}

export interface SessionDetail extends Session {
  assets: Asset[];
  event_count: number;
}

export interface CaptureEvent {
  seq: number;
  type: EventType;
  t_ms: number;
  selector?: string | null;
  text?: string | null;
  bbox?: [number, number, number, number] | null;
  value_redacted?: string | null;
}

export async function createSession(
  projectId: string,
  sourceType: SourceType,
  viewport?: { w: number; h: number },
): Promise<Session> {
  const r = await apiFetch(`/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: projectId, source_type: sourceType, viewport }),
  });
  if (!r.ok) throw new Error(`createSession failed: ${r.status}`);
  return r.json();
}

export async function registerAndUpload(
  sessionId: string,
  kind: "raw_video" | "audio" | "screenshot" | "frame",
  ext: string,
  blob: Blob,
): Promise<string> {
  const reg = await apiFetch(`/sessions/${sessionId}/assets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, ext }),
  });
  if (!reg.ok) throw new Error(`registerAsset failed: ${reg.status}`);
  const target = await reg.json();
  const put = await apiFetch(`${target.url}`, { method: "PUT", body: blob });
  if (!put.ok) throw new Error(`upload failed: ${put.status}`);
  return target.storage_key as string;
}

export async function postEvents(sessionId: string, events: CaptureEvent[]): Promise<void> {
  if (events.length === 0) return;
  const r = await apiFetch(`/sessions/${sessionId}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ events }),
  });
  if (!r.ok) throw new Error(`postEvents failed: ${r.status}`);
}

export async function completeSession(sessionId: string, durationMs?: number): Promise<Session> {
  const r = await apiFetch(`/sessions/${sessionId}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ duration_ms: durationMs ?? null }),
  });
  if (!r.ok) throw new Error(`completeSession failed: ${r.status}`);
  return r.json();
}

export async function listSessions(projectId?: string, scope: ListScope = "mine"): Promise<Session[]> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : `?scope=${scope}`;
  const r = await apiFetch(`/sessions${qs}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listSessions failed: ${r.status}`);
  return r.json();
}

// ---- pipeline status + workflow graph ----
export interface JobStatus {
  stage: string;
  version: number;
  status: string;
  attempts: number;
  error_json: Record<string, unknown> | null;
}

export interface SessionStatus {
  session_id: string;
  status: string;
  latest_version: number | null;
  jobs: JobStatus[];
}

export interface GraphStep {
  id: string;
  action: string;
  target: string;
  intent?: string | null;
  screen_name?: string | null;
  selector?: string | null;
  screenshot?: string | null;
  bbox?: [number, number, number, number] | null;
  narration?: string | null;
  t_start?: number | null;
  t_end?: number | null;
  confidence?: number | null;
  review_status?: string;
}

export interface WorkflowGraph {
  workflow_id: string;
  version: number;
  title: string;
  steps: GraphStep[];
  edges: { from: string; to: string; condition: string | null }[];
}

export interface GraphRow {
  id: string;
  project_id: string;
  version: number;
  graph_json: WorkflowGraph;
  created_at: string;
}

export async function getSessionStatus(sessionId: string): Promise<SessionStatus> {
  const r = await apiFetch(`/sessions/${sessionId}/status`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getSessionStatus failed: ${r.status}`);
  return r.json();
}

export async function reprocessSession(sessionId: string): Promise<Session> {
  const r = await apiFetch(`/sessions/${sessionId}/reprocess`, { method: "POST" });
  if (!r.ok) throw new Error(`reprocess failed: ${r.status}`);
  return r.json();
}

export async function getSessionDetail(sessionId: string): Promise<SessionDetail> {
  const r = await apiFetch(`/sessions/${sessionId}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getSessionDetail failed: ${r.status}`);
  return r.json();
}

export async function setTrim(
  sessionId: string,
  startMs: number,
  endMs: number,
): Promise<Session> {
  const r = await apiFetch(`/sessions/${sessionId}/trim`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start_ms: Math.round(startMs), end_ms: Math.round(endMs) }),
  });
  if (!r.ok) throw new Error(`setTrim failed: ${r.status}`);
  return r.json();
}

/** Approximate AI-generated output duration (ms) from an edit-spec. Mirrors the
 * render pipeline's timing rules exactly:
 *  - silent scene → full source length ÷ pace (same as a narrated scene)
 *  - narrated scene, AI voice → ~2.6 words/sec at voice speed · pace
 *  - narrated scene, original voice → source length ÷ pace
 *  - plus intro/outro; skipped scenes excluded. */
export function estimateOutputMs(spec: EditSpec): number {
  const WPS = 2.6;
  const pace = Math.min(1.5, Math.max(1, spec.pace ?? 1.0));
  const useOriginal = !!spec.voice.use_original;
  let body = 0;
  for (const s of spec.segments) {
    if (s.skipped) continue; // excluded from the render
    const srcMs = Math.max(0, s.source_end_ms - s.source_start_ms);
    const words = s.words.filter((_, i) => !s.removed.includes(i));
    if (words.length === 0) {
      body += Math.max(300, srcMs / pace);
    } else if (useOriginal) {
      body += Math.max(300, srcMs / pace);
    } else {
      body += Math.max(300, (words.length / (WPS * (spec.voice.speed || 1) * pace)) * 1000);
    }
  }
  const intro = spec.intro.enabled ? spec.intro.duration_ms : 0;
  const outro = spec.outro.enabled ? spec.outro.duration_ms : 0;
  return Math.round(body + intro + outro);
}

export interface MemoryStep {
  id: string;
  old_id: string | null;
  status: "added" | "changed" | "unchanged";
  target: string | null;
}

export interface Memory {
  has_prior: boolean;
  from_version?: number | null;
  to_version?: number | null;
  summary: { added: number; changed: number; unchanged: number; removed: number };
  steps: MemoryStep[];
  removed: { id: string; target: string | null }[];
}

export async function getMemory(projectId: string): Promise<Memory | null> {
  const r = await apiFetch(`/projects/${projectId}/memory`, { cache: "no-store" });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`getMemory failed: ${r.status}`);
  return r.json();
}

export async function getGraph(projectId: string, version?: number): Promise<GraphRow | null> {
  const qs = version != null ? `?version=${encodeURIComponent(version)}` : "";
  const r = await apiFetch(`/projects/${projectId}/graph${qs}`, { cache: "no-store" });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`getGraph failed: ${r.status}`);
  return r.json();
}

export function mediaUrl(storageKey: string): string {
  return `${API_BASE}/media/${storageKey}`;
}

/** Save a fetched body to disk. Cross-origin `<a download>` is ignored by
 *  browsers, so we go through a same-origin blob URL rather than navigating. */
async function saveBlob(response: Response, filename: string): Promise<void> {
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Media reads are public (so <video src> and share links work), hence a plain fetch.
export async function downloadMedia(storageKey: string, filename: string): Promise<void> {
  const r = await fetch(mediaUrl(storageKey));
  if (!r.ok) throw new Error(`download failed: ${r.status}`);
  await saveBlob(r, filename);
}

// ---- documents (SOP) ----
export interface DocStep {
  n: number;
  title: string;
  body: string;
  screenshot?: string | null;
}

export interface SopDoc {
  title: string;
  summary: string;
  graph_version: number;
  steps: DocStep[];
}

export interface DocumentResult {
  document_id: string;
  project_id: string;
  graph_version: number;
  doc: SopDoc;
}

export async function getDocument(projectId: string): Promise<DocumentResult | null> {
  const r = await apiFetch(`/projects/${projectId}/document`, { cache: "no-store" });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`getDocument failed: ${r.status}`);
  return r.json();
}

export async function regenerateDocument(
  projectId: string,
  instruction?: string,
): Promise<DocumentResult> {
  const r = await apiFetch(`/projects/${projectId}/document`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction: instruction ?? null }),
  });
  if (!r.ok) throw new Error(`regenerateDocument failed: ${r.status}`);
  return r.json();
}

/** Export the doc as MD/PDF. This is an authenticated route, so it can't be a
 *  plain `<a href>` — the browser wouldn't send the token. Fetch, then save. */
export async function downloadDocument(
  projectId: string,
  format: "md" | "pdf",
  filename: string,
): Promise<void> {
  const r = await apiFetch(`/projects/${projectId}/document/export?format=${format}`);
  if (!r.ok) throw new Error(`export failed: ${r.status}`);
  await saveBlob(r, filename);
}

// ---- publish & share ----
export interface Share {
  token: string;
  kind: "video" | "doc";
  revoked: boolean;
  created_at: string;
  project_id: string;
}

export interface SharePublic {
  kind: "video" | "doc";
  title: string;
  project_id: string;
  video_url: string | null;
  doc: SopDoc | null;
}

export function shareLink(token: string): string {
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  return `${origin}/share/${token}`;
}

export async function createShare(projectId: string, kind: "video" | "doc"): Promise<Share> {
  const r = await apiFetch(`/projects/${projectId}/share`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `share failed: ${r.status}`);
  return r.json();
}

export async function getSharePublic(token: string): Promise<SharePublic> {
  const r = await apiFetch(`/shares/${token}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getShare failed: ${r.status}`);
  const j = (await r.json()) as SharePublic;
  if (j.video_url && j.video_url.startsWith("/")) j.video_url = `${API_BASE}${j.video_url}`;
  return j;
}

export async function listAllShares(): Promise<Share[]> {
  const r = await apiFetch(`/shares`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listShares failed: ${r.status}`);
  return r.json();
}

export async function revokeShare(token: string): Promise<void> {
  await apiFetch(`/shares/${token}`, { method: "DELETE" });
}

// ---- AI voices ----
export interface Voice {
  id: string;
  name: string;
  gender: string;
  accent?: string;
  style: string;
}

export async function listVoices(): Promise<{ voices: Voice[]; preview_text: string }> {
  const r = await apiFetch(`/voices`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listVoices failed: ${r.status}`);
  return r.json();
}

export async function previewVoice(voiceId: string): Promise<{ url: string; ready: boolean }> {
  const r = await apiFetch(`/voices/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ voice_id: voiceId }),
  });
  if (!r.ok) throw new Error(`previewVoice failed: ${r.status}`);
  const j = await r.json();
  return { url: `${API_BASE}${j.url}`, ready: j.ready };
}

// ---- auto-edit (speed-up + zoom on the raw video) ----
export interface AutoEditJob {
  id: string;
  status: string;
  output_key: string | null;
  output_url: string | null;
  stats_json: Record<string, number> | null;
  error_json: Record<string, unknown> | null;
}

export interface AutoEditOptions {
  aggressiveness: "gentle" | "balanced" | "aggressive";
  captions: boolean;
  zoom: boolean;
}

export async function startAutoEdit(
  projectId: string,
  opts: AutoEditOptions,
): Promise<AutoEditJob> {
  const r = await apiFetch(`/projects/${projectId}/autoedit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opts),
  });
  if (!r.ok) throw new Error(`startAutoEdit failed: ${r.status}`);
  return r.json();
}

export async function getAutoEdit(jobId: string): Promise<AutoEditJob> {
  const r = await apiFetch(`/autoedit/${jobId}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getAutoEdit failed: ${r.status}`);
  return r.json();
}

// ---- AI script rewrite ----
export async function rewriteLines(
  projectId: string,
  lines: string[],
  instruction?: string,
): Promise<string[]> {
  const r = await apiFetch(`/projects/${projectId}/rewrite`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lines, instruction: instruction ?? null }),
  });
  if (!r.ok) {
    let detail = `rewrite failed: ${r.status}`;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await r.json()).lines as string[];
}

export async function generateScript(
  projectId: string,
  scenes: { target?: string; action?: string; narration?: string; seconds?: number }[],
  title: string,
  instruction?: string,
): Promise<string[]> {
  const r = await apiFetch(`/projects/${projectId}/generate-script`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenes, title, instruction: instruction ?? null }),
  });
  if (!r.ok) {
    let detail = `generate failed: ${r.status}`;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await r.json()).lines as string[];
}

export async function suggestZooms(
  projectId: string,
  scenes: { target?: string; action?: string; narration?: string }[],
): Promise<{ zoom: boolean; scale: number }[]> {
  const r = await apiFetch(`/projects/${projectId}/suggest-zooms`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenes }),
  });
  if (!r.ok) {
    let detail = `suggest failed: ${r.status}`;
    try {
      detail = (await r.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await r.json()).zooms as { zoom: boolean; scale: number }[];
}

// ---- skills ----
export interface Skill {
  id: string;
  name: string;
  description: string;
  target: "video" | "doc";
  settings: Record<string, unknown>;
}
export async function listSkills(scope: ListScope = "mine"): Promise<Skill[]> {
  const r = await apiFetch(`/skills?scope=${scope}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listSkills failed: ${r.status}`);
  return r.json();
}
export type SkillInput = {
  name: string;
  description?: string;
  target?: string;
  settings?: Record<string, unknown>;
};
export async function createSkill(s: SkillInput): Promise<Skill> {
  const r = await apiFetch(`/skills`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(s),
  });
  if (!r.ok) throw new Error(`createSkill failed: ${r.status}`);
  return r.json();
}
export async function generateSkill(prompt: string, target: string): Promise<Skill> {
  const r = await apiFetch(`/skills/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, target }),
  });
  if (!r.ok) {
    let d = `generate failed: ${r.status}`;
    try {
      d = (await r.json()).detail ?? d;
    } catch {
      /* ignore */
    }
    throw new Error(d);
  }
  return r.json();
}
export async function getSkill(id: string): Promise<Skill> {
  const r = await apiFetch(`/skills/${id}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getSkill failed: ${r.status}`);
  return r.json();
}
export async function updateSkill(id: string, s: SkillInput): Promise<Skill> {
  const r = await apiFetch(`/skills/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(s),
  });
  if (!r.ok) throw new Error(`updateSkill failed: ${r.status}`);
  return r.json();
}
export async function deleteSkill(id: string): Promise<void> {
  await apiFetch(`/skills/${id}`, { method: "DELETE" });
}

// ---- knowledge base ----
export interface Article {
  id: string;
  title: string;
  summary: string;
  body_md: string;
  tags: string[];
  project_id?: string | null;
}
export async function listArticles(scope: ListScope = "mine"): Promise<Article[]> {
  const r = await apiFetch(`/kb?scope=${scope}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listArticles failed: ${r.status}`);
  return r.json();
}
export async function createArticle(a: {
  title: string;
  summary?: string;
  body_md?: string;
  tags?: string[];
}): Promise<Article> {
  const r = await apiFetch(`/kb`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(a),
  });
  if (!r.ok) throw new Error(`createArticle failed: ${r.status}`);
  return r.json();
}
export async function deleteArticle(id: string): Promise<void> {
  await apiFetch(`/kb/${id}`, { method: "DELETE" });
}

// ---- brand packages ----
export interface BrandPackage {
  id: string;
  name: string;
  settings: Record<string, unknown>;
}
export async function listPackages(scope: ListScope = "mine"): Promise<BrandPackage[]> {
  const r = await apiFetch(`/packages?scope=${scope}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listPackages failed: ${r.status}`);
  return r.json();
}
export async function getPackage(id: string): Promise<BrandPackage> {
  const r = await apiFetch(`/packages/${id}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getPackage failed: ${r.status}`);
  return r.json();
}
/** Upload a File to a storage key (logo / intro clip) via the media endpoint. */
export async function uploadMedia(key: string, file: File): Promise<string> {
  const r = await apiFetch(`/media/${key}`, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!r.ok) throw new Error(`upload failed: ${r.status}`);
  return key;
}
export async function createPackage(name: string, settings: Record<string, unknown>): Promise<BrandPackage> {
  const r = await apiFetch(`/packages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, settings }),
  });
  if (!r.ok) throw new Error(`createPackage failed: ${r.status}`);
  return r.json();
}
export async function updatePackage(id: string, name: string, settings: Record<string, unknown>): Promise<BrandPackage> {
  const r = await apiFetch(`/packages/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, settings }),
  });
  if (!r.ok) throw new Error(`updatePackage failed: ${r.status}`);
  return r.json();
}
export async function deletePackage(id: string): Promise<void> {
  await apiFetch(`/packages/${id}`, { method: "DELETE" });
}

// ---- video editor / render ----
export interface EditSegment {
  step_id: string;
  action?: string;
  target?: string;
  words: string[];
  removed: number[];
  zoom: { enabled: boolean; scale: number; cx: number; cy: number; speed?: number; auto?: boolean };
  source_start_ms: number;
  source_end_ms: number;
  screenshot?: string | null;
  dirty?: boolean;
  skipped?: boolean; // greyed-out: kept in place on the timeline but skipped on playback + excluded from render
}

export interface EditElement {
  id: string;
  type: "text" | "box";
  x: number;
  y: number;
  w: number;
  h: number;
  text?: string;
  color?: string;
  size?: number; // text height as a fraction of the frame (e.g. 0.06)
  start_ms?: number; // optional time window (source ms); when end_ms>start_ms the
  end_ms?: number; //   element only shows during [start_ms, end_ms], else whole video
}

export interface CropRegion {
  enabled: boolean;
  x: number; // normalized (0..1) region of the ORIGINAL frame
  y: number;
  w: number;
  h: number;
  start_ms?: number; // optional time window: crop applies only within
  end_ms?: number; //   [start_ms, end_ms] when end>start, else whole video
}

/** All crops on a spec, with the legacy single `crop` folded in. */
export const cropList = (spec: { crop?: CropRegion; crops?: CropRegion[] }): CropRegion[] =>
  spec.crops ?? (spec.crop?.enabled ? [spec.crop] : []);

/** The crop in effect at a source-time (ms): first enabled region whose window
 * covers it; a region without a window applies everywhere. */
export const activeCrop = (crops: CropRegion[], atMs: number): CropRegion | undefined =>
  crops.find(
    (c) =>
      c.enabled &&
      ((c.end_ms ?? 0) <= (c.start_ms ?? 0) || (atMs >= (c.start_ms ?? 0) && atMs <= (c.end_ms ?? 0))),
  );

export interface EditSpec {
  graph_version: number;
  title: string;
  voice: { voice_id: string; speed: number; use_original?: boolean };
  aspect: "16:9" | "9:16" | "1:1";
  intro: { enabled: boolean; title: string; duration_ms: number };
  outro: { enabled: boolean; title: string; duration_ms: number };
  captions: { enabled: boolean };
  music: { enabled: boolean; storage_key: string | null; gain_db: number };
  crop?: CropRegion; // legacy single crop — superseded by `crops`
  crops?: CropRegion[]; // multi-range crops: first enabled region whose window
  //   covers a moment wins; a region without a window applies everywhere
  trim?: { enabled: boolean; start_ms: number; end_ms: number };
  motion_zoom?: boolean; // auto-zoom on mouse/click activity at render time
  pace?: number; // product-video tempo for narrated scenes (1.0–1.5, default 1.1)
  background?: { enabled: boolean; style: string }; // backdrop behind the (inset) recording
  brand?: {
    logo_url?: string;
    primary_color?: string;
    accent_color?: string;
    font?: string;
    logo_position?: string;
  };
  elements?: EditElement[];
  segments: EditSegment[];
}

export interface VideoSpec {
  video_project_id: string;
  project_id: string;
  graph_version: number;
  edit_spec: EditSpec;
  source_video?: string | null;
}

export interface RenderJob {
  id: string;
  status: string;
  output_key: string | null;
  output_url: string | null;
  stats_json: Record<string, number | string> | null;
  error_json: Record<string, unknown> | null;
}

export async function getVideo(projectId: string): Promise<VideoSpec | null> {
  const r = await apiFetch(`/projects/${projectId}/video`, { cache: "no-store" });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`getVideo failed: ${r.status}`);
  return r.json();
}

export async function patchVideo(projectId: string, editSpec: EditSpec): Promise<VideoSpec> {
  const r = await apiFetch(`/projects/${projectId}/video`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ edit_spec: editSpec }),
  });
  if (!r.ok) throw new Error(`patchVideo failed: ${r.status}`);
  return r.json();
}

/** One scene's slot on the render's OUTPUT clock — mirrors worker.pipeline.timeline.Segment.
 * `speed` = source_len / out_duration (>1 plays faster to fit; a real `hold`-free
 * scene where the voice outlasts the window instead holds its last frame, which
 * the player detects itself rather than trusting a stale flag here). */
export interface PreviewTimelineSegment {
  step_id: string;
  index: number;
  out_start_ms: number;
  out_end_ms: number;
  out_duration_ms: number;
  source_start_ms: number;
  source_end_ms: number;
  speed: number;
  hold: boolean;
}

export interface PreviewTimeline {
  total_duration_ms: number;
  segments: PreviewTimelineSegment[];
}

function _voiceRes(j: { url: string; ready: boolean; timeline_url?: string | null }) {
  return {
    url: j.url?.startsWith("/") ? `${API_BASE}${j.url}` : j.url,
    ready: !!j.ready,
    timelineUrl: j.timeline_url
      ? j.timeline_url.startsWith("/")
        ? `${API_BASE}${j.timeline_url}`
        : j.timeline_url
      : null,
  };
}

/** Kick off building the voice track (enqueues once). */
export async function startVoiceTrack(
  projectId: string,
  voiceId: string,
  speed: number,
): Promise<{ url: string; ready: boolean; timelineUrl: string | null }> {
  const r = await apiFetch(`/projects/${projectId}/voice-track`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ voice_id: voiceId, speed }),
  });
  if (!r.ok) throw new Error(`voice-track failed: ${r.status}`);
  return _voiceRes(await r.json());
}

/** Poll readiness (does not re-enqueue). */
export async function pollVoiceTrack(
  projectId: string,
  voiceId: string,
  speed: number,
): Promise<{ url: string; ready: boolean; timelineUrl: string | null }> {
  const q = `voice_id=${encodeURIComponent(voiceId)}&speed=${speed}`;
  const r = await apiFetch(`/projects/${projectId}/voice-track?${q}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`voice-track poll failed: ${r.status}`);
  return _voiceRes(await r.json());
}

/** Fetch and parse a preview timeline JSON (from `timelineUrl`). */
export async function fetchPreviewTimeline(url: string): Promise<PreviewTimeline> {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`preview timeline fetch failed: ${r.status}`);
  return r.json();
}

export async function renderVideo(projectId: string): Promise<RenderJob> {
  const r = await apiFetch(`/projects/${projectId}/video/render`, { method: "POST" });
  if (!r.ok) throw new Error(`renderVideo failed: ${r.status}`);
  return r.json();
}

export async function getRender(jobId: string): Promise<RenderJob> {
  const r = await apiFetch(`/render/${jobId}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getRender failed: ${r.status}`);
  return r.json();
}

// ---- admin (all routes 403 for non-admins) ----
export interface AdminUser {
  id: string;
  email: string;
  name: string;
  role: "user" | "admin" | null;
  created_at: string;
  project_count: number;
}

export async function listUsers(): Promise<AdminUser[]> {
  const r = await apiFetch(`/admin/users`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listUsers failed: ${r.status}`);
  return r.json();
}

export interface UsageSummary {
  videos_generated: number;
  screens_recorded: number;
  videos_uploaded: number;
  video_duration_ms: number; // combined length of the generated videos in range
  recording_duration_ms: number; // combined length of the screen recordings in range
  upload_duration_ms: number; // combined length of the uploaded videos in range
  from_date: string | null;
  to_date: string | null;
}

/** Usage totals, optionally limited to an inclusive from/to date range (YYYY-MM-DD). */
export async function getUsageSummary(from?: string, to?: string): Promise<UsageSummary> {
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  const qs = params.toString();
  const r = await apiFetch(`/admin/usage${qs ? `?${qs}` : ""}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getUsageSummary failed: ${r.status}`);
  return r.json();
}

export interface UsageEventRow {
  kind: "video" | "recording" | "upload";
  user_email: string | null;
  user_name: string | null;
  duration_ms: number | null;
  created_at: string;
}

export interface UsageEventsPage {
  total: number; // events matching the range, across all pages
  events: UsageEventRow[];
}

/** One page of per-event usage detail (who did what, when), newest first. */
export async function listUsageEvents(
  from?: string,
  to?: string,
  limit = 25,
  offset = 0,
): Promise<UsageEventsPage> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  const r = await apiFetch(`/admin/usage/events?${params}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listUsageEvents failed: ${r.status}`);
  return r.json();
}

export async function setUserRole(userId: string, role: "user" | "admin"): Promise<AdminUser> {
  const r = await apiFetch(`/admin/users/${userId}/role`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
  if (!r.ok) {
    const detail = await r.json().then((d) => d?.detail).catch(() => null);
    throw new Error(typeof detail === "string" ? detail : `setUserRole failed: ${r.status}`);
  }
  return r.json();
}
