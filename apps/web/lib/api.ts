export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export interface Project {
  id: string;
  name: string;
  favorite?: number; // 0/1 — starred projects sort first
  created_at: string;
}

export async function setKeepRanges(sessionId: string, ranges: number[][]): Promise<void> {
  const r = await fetch(`${API_BASE}/sessions/${sessionId}/keep-ranges`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ranges }),
  });
  if (!r.ok) throw new Error(`setKeepRanges failed: ${r.status}`);
}

export async function toggleFavorite(projectId: string): Promise<Project> {
  const r = await fetch(`${API_BASE}/projects/${projectId}/favorite`, { method: "POST" });
  if (!r.ok) throw new Error(`toggleFavorite failed: ${r.status}`);
  return r.json();
}

export async function listProjects(): Promise<Project[]> {
  const r = await fetch(`${API_BASE}/projects`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listProjects failed: ${r.status}`);
  return r.json();
}

export async function getProject(id: string): Promise<Project> {
  const r = await fetch(`${API_BASE}/projects/${id}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getProject failed: ${r.status}`);
  return r.json();
}

export async function createProject(name: string): Promise<Project> {
  const r = await fetch(`${API_BASE}/projects`, {
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
  const r = await fetch(`${API_BASE}/sessions`, {
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
  const reg = await fetch(`${API_BASE}/sessions/${sessionId}/assets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, ext }),
  });
  if (!reg.ok) throw new Error(`registerAsset failed: ${reg.status}`);
  const target = await reg.json();
  const put = await fetch(`${API_BASE}${target.url}`, { method: "PUT", body: blob });
  if (!put.ok) throw new Error(`upload failed: ${put.status}`);
  return target.storage_key as string;
}

export async function postEvents(sessionId: string, events: CaptureEvent[]): Promise<void> {
  if (events.length === 0) return;
  const r = await fetch(`${API_BASE}/sessions/${sessionId}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ events }),
  });
  if (!r.ok) throw new Error(`postEvents failed: ${r.status}`);
}

export async function completeSession(sessionId: string, durationMs?: number): Promise<Session> {
  const r = await fetch(`${API_BASE}/sessions/${sessionId}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ duration_ms: durationMs ?? null }),
  });
  if (!r.ok) throw new Error(`completeSession failed: ${r.status}`);
  return r.json();
}

export async function listSessions(projectId?: string): Promise<Session[]> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  const r = await fetch(`${API_BASE}/sessions${qs}`, { cache: "no-store" });
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
  const r = await fetch(`${API_BASE}/sessions/${sessionId}/status`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getSessionStatus failed: ${r.status}`);
  return r.json();
}

export async function reprocessSession(sessionId: string): Promise<Session> {
  const r = await fetch(`${API_BASE}/sessions/${sessionId}/reprocess`, { method: "POST" });
  if (!r.ok) throw new Error(`reprocess failed: ${r.status}`);
  return r.json();
}

export async function getSessionDetail(sessionId: string): Promise<SessionDetail> {
  const r = await fetch(`${API_BASE}/sessions/${sessionId}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getSessionDetail failed: ${r.status}`);
  return r.json();
}

export async function setTrim(
  sessionId: string,
  startMs: number,
  endMs: number,
): Promise<Session> {
  const r = await fetch(`${API_BASE}/sessions/${sessionId}/trim`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start_ms: Math.round(startMs), end_ms: Math.round(endMs) }),
  });
  if (!r.ok) throw new Error(`setTrim failed: ${r.status}`);
  return r.json();
}

/** Approximate AI-generated output duration (ms) from an edit-spec: ~2.6 words/sec
 * of effective narration per step, plus intro/outro. Mirrors the TTS estimator. */
export function estimateOutputMs(spec: EditSpec): number {
  const WPS = 2.6;
  let body = 0;
  for (const s of spec.segments) {
    const words = s.words.filter((_, i) => !s.removed.includes(i));
    const secs = Math.max(0.3, words.length / (WPS * (spec.voice.speed || 1)));
    body += secs * 1000;
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
  const r = await fetch(`${API_BASE}/projects/${projectId}/memory`, { cache: "no-store" });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`getMemory failed: ${r.status}`);
  return r.json();
}

export async function getGraph(projectId: string, version?: number): Promise<GraphRow | null> {
  const url = new URL(`${API_BASE}/projects/${projectId}/graph`);
  if (version != null) url.searchParams.set("version", String(version));
  const r = await fetch(url.toString(), { cache: "no-store" });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`getGraph failed: ${r.status}`);
  return r.json();
}

export function mediaUrl(storageKey: string): string {
  return `${API_BASE}/media/${storageKey}`;
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
  const r = await fetch(`${API_BASE}/projects/${projectId}/document`, { cache: "no-store" });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`getDocument failed: ${r.status}`);
  return r.json();
}

export async function regenerateDocument(
  projectId: string,
  instruction?: string,
): Promise<DocumentResult> {
  const r = await fetch(`${API_BASE}/projects/${projectId}/document`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction: instruction ?? null }),
  });
  if (!r.ok) throw new Error(`regenerateDocument failed: ${r.status}`);
  return r.json();
}

export function docExportUrl(projectId: string, format: "md" | "pdf"): string {
  return `${API_BASE}/projects/${projectId}/document/export?format=${format}`;
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
  const r = await fetch(`${API_BASE}/projects/${projectId}/share`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind }),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `share failed: ${r.status}`);
  return r.json();
}

export async function getSharePublic(token: string): Promise<SharePublic> {
  const r = await fetch(`${API_BASE}/shares/${token}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getShare failed: ${r.status}`);
  const j = (await r.json()) as SharePublic;
  if (j.video_url && j.video_url.startsWith("/")) j.video_url = `${API_BASE}${j.video_url}`;
  return j;
}

export async function listAllShares(): Promise<Share[]> {
  const r = await fetch(`${API_BASE}/shares`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listShares failed: ${r.status}`);
  return r.json();
}

export async function revokeShare(token: string): Promise<void> {
  await fetch(`${API_BASE}/shares/${token}`, { method: "DELETE" });
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
  const r = await fetch(`${API_BASE}/voices`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listVoices failed: ${r.status}`);
  return r.json();
}

export async function previewVoice(voiceId: string): Promise<{ url: string; ready: boolean }> {
  const r = await fetch(`${API_BASE}/voices/preview`, {
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
  const r = await fetch(`${API_BASE}/projects/${projectId}/autoedit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(opts),
  });
  if (!r.ok) throw new Error(`startAutoEdit failed: ${r.status}`);
  return r.json();
}

export async function getAutoEdit(jobId: string): Promise<AutoEditJob> {
  const r = await fetch(`${API_BASE}/autoedit/${jobId}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getAutoEdit failed: ${r.status}`);
  return r.json();
}

// ---- AI script rewrite ----
export async function rewriteLines(
  projectId: string,
  lines: string[],
  instruction?: string,
): Promise<string[]> {
  const r = await fetch(`${API_BASE}/projects/${projectId}/rewrite`, {
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
  scenes: { target?: string; action?: string; narration?: string }[],
  title: string,
  instruction?: string,
): Promise<string[]> {
  const r = await fetch(`${API_BASE}/projects/${projectId}/generate-script`, {
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
  const r = await fetch(`${API_BASE}/projects/${projectId}/suggest-zooms`, {
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
export async function listSkills(): Promise<Skill[]> {
  const r = await fetch(`${API_BASE}/skills`, { cache: "no-store" });
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
  const r = await fetch(`${API_BASE}/skills`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(s),
  });
  if (!r.ok) throw new Error(`createSkill failed: ${r.status}`);
  return r.json();
}
export async function generateSkill(prompt: string, target: string): Promise<Skill> {
  const r = await fetch(`${API_BASE}/skills/generate`, {
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
  const r = await fetch(`${API_BASE}/skills/${id}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getSkill failed: ${r.status}`);
  return r.json();
}
export async function updateSkill(id: string, s: SkillInput): Promise<Skill> {
  const r = await fetch(`${API_BASE}/skills/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(s),
  });
  if (!r.ok) throw new Error(`updateSkill failed: ${r.status}`);
  return r.json();
}
export async function deleteSkill(id: string): Promise<void> {
  await fetch(`${API_BASE}/skills/${id}`, { method: "DELETE" });
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
export async function listArticles(): Promise<Article[]> {
  const r = await fetch(`${API_BASE}/kb`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listArticles failed: ${r.status}`);
  return r.json();
}
export async function createArticle(a: {
  title: string;
  summary?: string;
  body_md?: string;
  tags?: string[];
}): Promise<Article> {
  const r = await fetch(`${API_BASE}/kb`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(a),
  });
  if (!r.ok) throw new Error(`createArticle failed: ${r.status}`);
  return r.json();
}
export async function deleteArticle(id: string): Promise<void> {
  await fetch(`${API_BASE}/kb/${id}`, { method: "DELETE" });
}

// ---- brand packages ----
export interface BrandPackage {
  id: string;
  name: string;
  settings: Record<string, unknown>;
}
export async function listPackages(): Promise<BrandPackage[]> {
  const r = await fetch(`${API_BASE}/packages`, { cache: "no-store" });
  if (!r.ok) throw new Error(`listPackages failed: ${r.status}`);
  return r.json();
}
export async function getPackage(id: string): Promise<BrandPackage> {
  const r = await fetch(`${API_BASE}/packages/${id}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getPackage failed: ${r.status}`);
  return r.json();
}
/** Upload a File to a storage key (logo / intro clip) via the media endpoint. */
export async function uploadMedia(key: string, file: File): Promise<string> {
  const r = await fetch(`${API_BASE}/media/${key}`, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!r.ok) throw new Error(`upload failed: ${r.status}`);
  return key;
}
export async function createPackage(name: string, settings: Record<string, unknown>): Promise<BrandPackage> {
  const r = await fetch(`${API_BASE}/packages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, settings }),
  });
  if (!r.ok) throw new Error(`createPackage failed: ${r.status}`);
  return r.json();
}
export async function updatePackage(id: string, name: string, settings: Record<string, unknown>): Promise<BrandPackage> {
  const r = await fetch(`${API_BASE}/packages/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, settings }),
  });
  if (!r.ok) throw new Error(`updatePackage failed: ${r.status}`);
  return r.json();
}
export async function deletePackage(id: string): Promise<void> {
  await fetch(`${API_BASE}/packages/${id}`, { method: "DELETE" });
}

// ---- video editor / render ----
export interface EditSegment {
  step_id: string;
  action?: string;
  target?: string;
  words: string[];
  removed: number[];
  zoom: { enabled: boolean; scale: number; cx: number; cy: number; speed?: number };
  source_start_ms: number;
  source_end_ms: number;
  screenshot?: string | null;
  dirty?: boolean;
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

export interface EditSpec {
  graph_version: number;
  title: string;
  voice: { voice_id: string; speed: number; use_original?: boolean };
  aspect: "16:9" | "9:16" | "1:1";
  intro: { enabled: boolean; title: string; duration_ms: number };
  outro: { enabled: boolean; title: string; duration_ms: number };
  captions: { enabled: boolean };
  music: { enabled: boolean; storage_key: string | null; gain_db: number };
  crop?: { enabled: boolean; x: number; y: number; w: number; h: number };
  trim?: { enabled: boolean; start_ms: number; end_ms: number };
  motion_zoom?: boolean; // auto-zoom on mouse/click activity at render time
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
  const r = await fetch(`${API_BASE}/projects/${projectId}/video`, { cache: "no-store" });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`getVideo failed: ${r.status}`);
  return r.json();
}

export async function patchVideo(projectId: string, editSpec: EditSpec): Promise<VideoSpec> {
  const r = await fetch(`${API_BASE}/projects/${projectId}/video`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ edit_spec: editSpec }),
  });
  if (!r.ok) throw new Error(`patchVideo failed: ${r.status}`);
  return r.json();
}

function _voiceRes(j: { url: string; ready: boolean }) {
  return { url: j.url?.startsWith("/") ? `${API_BASE}${j.url}` : j.url, ready: !!j.ready };
}

/** Kick off building the voice track (enqueues once). */
export async function startVoiceTrack(
  projectId: string,
  voiceId: string,
  speed: number,
): Promise<{ url: string; ready: boolean }> {
  const r = await fetch(`${API_BASE}/projects/${projectId}/voice-track`, {
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
): Promise<{ url: string; ready: boolean }> {
  const q = `voice_id=${encodeURIComponent(voiceId)}&speed=${speed}`;
  const r = await fetch(`${API_BASE}/projects/${projectId}/voice-track?${q}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`voice-track poll failed: ${r.status}`);
  return _voiceRes(await r.json());
}

export async function renderVideo(projectId: string): Promise<RenderJob> {
  const r = await fetch(`${API_BASE}/projects/${projectId}/video/render`, { method: "POST" });
  if (!r.ok) throw new Error(`renderVideo failed: ${r.status}`);
  return r.json();
}

export async function getRender(jobId: string): Promise<RenderJob> {
  const r = await fetch(`${API_BASE}/render/${jobId}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`getRender failed: ${r.status}`);
  return r.json();
}
