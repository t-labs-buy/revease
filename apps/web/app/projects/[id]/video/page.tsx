"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  getRender,
  getVideo,
  mediaUrl,
  patchVideo,
  generateScript,
  pollVoiceTrack,
  renderVideo,
  rewriteLines,
  startVoiceTrack,
  suggestZooms,
  type EditElement,
  type EditSegment,
  type EditSpec,
  type RenderJob,
} from "@/lib/api";
import { Spinner } from "@/components/ui";
import { VoicePanel } from "@/components/VoicePanel";
import { ShareButton } from "@/components/ShareButton";
import { PreviewOverlay } from "@/components/PreviewOverlay";
import { CropModal, TrimModal } from "@/components/EditModals";

type Tone = "Professional" | "Casual" | "Energetic" | "Concise";
const TONES: Tone[] = ["Professional", "Casual", "Energetic", "Concise"];
const TONE_INSTR: Record<Tone, string> = {
  Professional: "Use a polished, professional, confident tone.",
  Casual: "Use a friendly, casual, conversational tone.",
  Energetic: "Use an upbeat, energetic, enthusiastic tone.",
  Concise: "Make each line as concise as possible while keeping the meaning.",
};
const ENHANCE_INSTR =
  "Tighten every line: remove filler, redundancy and hedging, fix awkward phrasing, and " +
  "make it crisp, natural to speak, and demo-ready. Keep all product and feature names.";

type Tab = "Script" | "AI Voice" | "Zoom" | "Trim" | "Crop" | "Elements" | "Captions";
const SIDE_TABS: Tab[] = ["Script", "AI Voice", "Zoom"];
const TOOL_TABS: Tab[] = ["Elements"];

const eff = (s: EditSegment) => s.words.filter((_, i) => !s.removed.includes(i)).join(" ");
const tokenize = (text: string) => text.trim().split(/\s+/).filter(Boolean);
const wordTimeSec = (s: EditSegment, wi: number) => {
  const start = s.source_start_ms;
  const end = Math.max(s.source_end_ms, start + 300);
  const n = Math.max(1, s.words.length);
  return (start + ((end - start) * wi) / n) / 1000;
};
const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const clock = (t: number) =>
  `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(Math.floor(t % 60)).padStart(2, "0")}.${String(
    Math.floor((t % 1) * 100),
  ).padStart(2, "0")}`;

export default function VideoEditor({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [spec, setSpec] = useState<EditSpec | null>(null);
  const [savedSpec, setSavedSpec] = useState<EditSpec | null>(null);
  const [source, setSource] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("Script");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [voiceNonce, setVoiceNonce] = useState(0);
  const [render, setRender] = useState<RenderJob | null>(null);
  const [rendering, setRendering] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [q, setQ] = useState("");
  const [editIdx, setEditIdx] = useState<number | null>(null);
  const [zoomIdx, setZoomIdx] = useState<number | null>(null);
  const [selEl, setSelEl] = useState<string | null>(null);
  const [rate, setRate] = useState(1);
  const [tlZoom, setTlZoom] = useState(1);
  const [rewriting, setRewriting] = useState<null | "all" | "enhance" | "gen" | number>(null);
  const [tone, setTone] = useState<Tone>("Professional");
  const [zoomBusy, setZoomBusy] = useState(false);
  const [activeTool, setActiveTool] = useState<null | "trim" | "crop">(null); // inline preview tools

  // undo / redo history (coalesced snapshots of the whole edit-spec)
  const past = useRef<EditSpec[]>([]);
  const future = useRef<EditSpec[]>([]);
  const baseline = useRef<EditSpec | null>(null);
  const skipHist = useRef(false);
  const [histState, setHistState] = useState({ canUndo: false, canRedo: false });
  const refreshHist = useCallback(
    () => setHistState({ canUndo: past.current.length > 0, canRedo: future.current.length > 0 }),
    [],
  );

  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const activeRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const [frameSize, setFrameSize] = useState({ w: 0, h: 0 });
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [showRender, setShowRender] = useState(false);
  const [voiceUrl, setVoiceUrl] = useState<string | null>(null);
  const [voiceLoading, setVoiceLoading] = useState(false);
  const [voiceError, setVoiceError] = useState(false);

  const voiceKey = spec?.voice.voice_id;
  const voiceSpeed = spec?.voice.speed;
  const useOriginal = spec?.voice.use_original;
  const wantAiVoice = !!spec && !useOriginal;
  const aiVoiceActive = !!voiceUrl && wantAiVoice;
  const dirty = !!spec && !!savedSpec && JSON.stringify(spec) !== JSON.stringify(savedSpec);

  useEffect(() => {
    if (!spec || useOriginal) {
      setVoiceUrl(null);
      setVoiceError(false);
      return;
    }
    let cancelled = false;
    setVoiceLoading(true);
    setVoiceError(false);
    setVoiceUrl(null);
    (async () => {
      try {
        await patchVideo(id, spec);
        const started = await startVoiceTrack(id, voiceKey!, voiceSpeed!);
        if (started.ready) {
          if (!cancelled) {
            setVoiceUrl(started.url);
            setVoiceLoading(false);
          }
          return;
        }
        for (let i = 0; i < 80 && !cancelled; i++) {
          await new Promise((r) => setTimeout(r, 1500));
          const { url, ready } = await pollVoiceTrack(id, voiceKey!, voiceSpeed!);
          if (ready) {
            if (!cancelled) {
              setVoiceUrl(url);
              setVoiceLoading(false);
            }
            return;
          }
        }
        if (!cancelled) setVoiceError(true);
      } catch {
        if (!cancelled) setVoiceError(true);
      } finally {
        if (!cancelled) setVoiceLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, voiceKey, voiceSpeed, useOriginal, voiceNonce]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.muted = wantAiVoice;
  }, [wantAiVoice, source, showRender, voiceUrl]);

  useEffect(() => {
    const a = audioRef.current;
    const v = videoRef.current;
    if (!a) return;
    if (playing && aiVoiceActive) {
      if (v) a.currentTime = v.currentTime;
      void a.play().catch(() => {});
    } else {
      a.pause();
    }
  }, [playing, aiVoiceActive, voiceUrl]);

  // keep playback rate in sync
  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = rate;
    if (audioRef.current) audioRef.current.playbackRate = rate;
  }, [rate, voiceUrl, source]);

  useEffect(() => {
    setSpec(null);
    setSavedSpec(null);
    setSource(null);
    setVoiceUrl(null);
    setVoiceError(false);
    // reset undo history for the new project
    past.current = [];
    future.current = [];
    baseline.current = null;
    setHistState({ canUndo: false, canRedo: false });
    getVideo(id)
      .then((v) => {
        setSpec(v?.edit_spec ?? null);
        setSavedSpec(v?.edit_spec ?? null);
        setSource(v?.source_video ?? null);
        baseline.current = v?.edit_spec ?? null;
      })
      .catch((e) => setError(String(e)));
  }, [id]);

  // Record a history snapshot once edits settle (coalesces drags/typing into one step).
  useEffect(() => {
    if (!spec) return;
    if (skipHist.current) {
      skipHist.current = false;
      baseline.current = spec;
      return;
    }
    if (baseline.current === null) {
      baseline.current = spec;
      return;
    }
    const t = setTimeout(() => {
      if (baseline.current && JSON.stringify(baseline.current) !== JSON.stringify(spec)) {
        past.current.push(baseline.current);
        if (past.current.length > 80) past.current.shift();
        future.current = [];
        baseline.current = spec;
        refreshHist();
      }
    }, 450);
    return () => clearTimeout(t);
  }, [spec, refreshHist]);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const mutateSeg = useCallback((idx: number, patch: Partial<EditSegment>) => {
    setSpec((s) =>
      s ? { ...s, segments: s.segments.map((seg, i) => (i === idx ? { ...seg, ...patch } : seg)) } : s,
    );
  }, []);

  const patchSpec = useCallback((patch: Partial<EditSpec>) => {
    setSpec((s) => (s ? { ...s, ...patch } : s));
  }, []);

  const setSegText = useCallback(
    (idx: number, text: string) => mutateSeg(idx, { words: tokenize(text), removed: [] }),
    [mutateSeg],
  );

  const addSegment = useCallback(() => {
    setSpec((s) => {
      if (!s) return s;
      const last = s.segments[s.segments.length - 1];
      const start = last ? last.source_start_ms : 0;
      const end = last ? last.source_end_ms : 3000;
      const seg: EditSegment = {
        step_id: `manual_${Date.now()}`,
        action: "note",
        target: "Added line",
        words: [],
        removed: [],
        zoom: { enabled: false, scale: 1.6, cx: 0.5, cy: 0.5 },
        source_start_ms: start,
        source_end_ms: end,
      };
      setEditIdx(s.segments.length);
      return { ...s, segments: [...s.segments, seg] };
    });
  }, []);

  const deleteSegment = useCallback((idx: number) => {
    setEditIdx(null);
    setSpec((s) => (s ? { ...s, segments: s.segments.filter((_, i) => i !== idx) } : s));
  }, []);

  const duplicateSegment = useCallback((idx: number) => {
    setSpec((s) => {
      if (!s || !s.segments[idx]) return s;
      const copy = { ...s.segments[idx], step_id: `dup_${Date.now()}` };
      const arr = [...s.segments];
      arr.splice(idx + 1, 0, copy);
      return { ...s, segments: arr };
    });
  }, []);

  // Drag a scene along the timeline (move its source window) / resize its length.
  const moveSegment = useCallback((idx: number, startMs: number) => {
    setSpec((s) => {
      if (!s || !s.segments[idx]) return s;
      const seg = s.segments[idx];
      const len = Math.max(300, seg.source_end_ms - seg.source_start_ms);
      const start = Math.round(Math.max(0, startMs));
      return {
        ...s,
        segments: s.segments.map((g, i) =>
          i === idx ? { ...g, source_start_ms: start, source_end_ms: start + len } : g,
        ),
      };
    });
  }, []);
  const resizeSegment = useCallback((idx: number, endMs: number) => {
    setSpec((s) => {
      if (!s || !s.segments[idx]) return s;
      const seg = s.segments[idx];
      const end = Math.round(Math.max(seg.source_start_ms + 300, endMs));
      return {
        ...s,
        segments: s.segments.map((g, i) => (i === idx ? { ...g, source_end_ms: end } : g)),
      };
    });
  }, []);

  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const update = () => setFrameSize({ w: el.clientWidth, h: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [source, showRender]);

  const addElement = useCallback((type: EditElement["type"]) => {
    const el: EditElement =
      type === "text"
        ? { id: `el_${Date.now()}`, type, x: 0.1, y: 0.08, w: 0.5, h: 0.12, text: "Your text", color: "#111827", size: 0.07 }
        : { id: `el_${Date.now()}`, type, x: 0.35, y: 0.35, w: 0.3, h: 0.2, color: "#6d5dfb" };
    setSpec((s) => (s ? { ...s, elements: [...(s.elements ?? []), el] } : s));
    setSelEl(el.id);
  }, []);
  const updateElement = useCallback(
    (elId: string, patch: Partial<EditElement>) =>
      setSpec((s) =>
        s ? { ...s, elements: (s.elements ?? []).map((e) => (e.id === elId ? { ...e, ...patch } : e)) } : s,
      ),
    [],
  );
  const deleteElement = useCallback((elId: string) => {
    setSelEl(null);
    setSpec((s) => (s ? { ...s, elements: (s.elements ?? []).filter((e) => e.id !== elId) } : s));
  }, []);

  const undo = useCallback(() => {
    if (!past.current.length) return;
    const prev = past.current.pop()!;
    if (baseline.current) future.current.push(baseline.current);
    skipHist.current = true;
    baseline.current = prev;
    setSpec(prev);
    setEditIdx(null);
    refreshHist();
  }, [refreshHist]);

  const redo = useCallback(() => {
    if (!future.current.length) return;
    const next = future.current.pop()!;
    if (baseline.current) past.current.push(baseline.current);
    skipHist.current = true;
    baseline.current = next;
    setSpec(next);
    setEditIdx(null);
    refreshHist();
  }, [refreshHist]);

  // keyboard: ⌘/Ctrl+Z undo, ⌘/Ctrl+Shift+Z or Ctrl+Y redo
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (!mod) return;
      const k = e.key.toLowerCase();
      if (k === "z" && !e.shiftKey) {
        e.preventDefault();
        undo();
      } else if ((k === "z" && e.shiftKey) || k === "y") {
        e.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);

  // Split a scene at the playhead into two scenes.
  const splitSegment = useCallback((idx: number, atMs: number) => {
    setSpec((s) => {
      if (!s || !s.segments[idx]) return s;
      const seg = s.segments[idx];
      if (atMs <= seg.source_start_ms + 150 || atMs >= seg.source_end_ms - 150) return s;
      const frac = (atMs - seg.source_start_ms) / (seg.source_end_ms - seg.source_start_ms);
      const wi = Math.round(seg.words.length * frac);
      const a: EditSegment = {
        ...seg,
        source_end_ms: Math.round(atMs),
        words: seg.words.slice(0, wi),
        removed: seg.removed.filter((r) => r < wi),
      };
      const b: EditSegment = {
        ...seg,
        step_id: `split_${Date.now()}`,
        source_start_ms: Math.round(atMs),
        words: seg.words.slice(wi),
        removed: seg.removed.filter((r) => r >= wi).map((r) => r - wi),
      };
      const arr = [...s.segments];
      arr.splice(idx, 1, a, b);
      return { ...s, segments: arr };
    });
  }, []);

  // AI rewrite: polish one line, or the whole script, via Claude.
  async function rewriteAll(instruction?: string, mode: "all" | "enhance" = "all") {
    if (!spec || rewriting !== null) return;
    setRewriting(mode);
    setError(null);
    try {
      const targets = spec.segments.map((s, i) => ({ i, t: eff(s) })).filter((x) => x.t.trim());
      if (!targets.length) return;
      const out = await rewriteLines(id, targets.map((x) => x.t), instruction ?? TONE_INSTR[tone]);
      setSpec((s) => {
        if (!s) return s;
        const segs = [...s.segments];
        targets.forEach((x, k) => {
          segs[x.i] = { ...segs[x.i], words: tokenize(out[k] || x.t), removed: [] };
        });
        return { ...s, segments: segs };
      });
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setRewriting(null);
    }
  }

  // One-click enhance: tighten the whole script + turn on captions.
  async function enhance() {
    if (!spec) return;
    setSpec((s) => (s ? { ...s, captions: { enabled: true } } : s));
    await rewriteAll(ENHANCE_INSTR, "enhance");
  }

  // Generate narration for scenes with none (using scene targets + the rest as context).
  async function genScript(fillEmptyOnly: boolean) {
    if (!spec || rewriting !== null) return;
    setRewriting("gen");
    setError(null);
    try {
      const scenes = spec.segments.map((s) => ({
        target: s.target ?? "",
        action: s.action ?? "",
        narration: eff(s),
      }));
      const lines = await generateScript(id, scenes, spec.title, TONE_INSTR[tone]);
      setSpec((s) => {
        if (!s) return s;
        const segs = s.segments.map((seg, i) => {
          if (fillEmptyOnly && eff(seg).trim()) return seg; // keep existing narration
          return { ...seg, words: tokenize(lines[i] || eff(seg)), removed: [] };
        });
        return { ...s, segments: segs };
      });
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setRewriting(null);
    }
  }

  // AI zoom: Claude picks which scenes to zoom and how much (keeps position).
  async function aiZooms() {
    if (!spec || zoomBusy) return;
    setZoomBusy(true);
    setError(null);
    try {
      const scenes = spec.segments.map((s) => ({
        target: s.target ?? "",
        action: s.action ?? "",
        narration: eff(s),
      }));
      const zs = await suggestZooms(id, scenes);
      setSpec((s) => {
        if (!s) return s;
        const segs = s.segments.map((seg, i) =>
          zs[i] ? { ...seg, zoom: { ...seg.zoom, enabled: zs[i].zoom, scale: zs[i].scale } } : seg,
        );
        return { ...s, segments: segs };
      });
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setZoomBusy(false);
    }
  }

  async function rewriteOne(i: number) {
    if (!spec || rewriting !== null) return;
    const t = eff(spec.segments[i]);
    if (!t.trim()) return;
    setRewriting(i);
    setError(null);
    try {
      const out = await rewriteLines(id, [t], TONE_INSTR[tone]);
      setSegText(i, out[0] || t);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setRewriting(null);
    }
  }

  async function save() {
    if (!spec) return;
    setSaving(true);
    try {
      const v = await patchVideo(id, spec);
      setSpec(v.edit_spec);
      setSavedSpec(v.edit_spec);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function discard() {
    if (!savedSpec) return;
    setSpec(savedSpec);
    setEditIdx(null);
    try {
      await patchVideo(id, savedSpec);
    } catch {
      /* non-fatal */
    }
    if (!savedSpec.voice.use_original) setVoiceNonce((n) => n + 1);
  }

  async function refreshVoice() {
    if (!spec) return;
    await save();
    setVoiceNonce((n) => n + 1);
  }

  async function doRender() {
    if (!spec) return;
    setRendering(true);
    setShowRender(true);
    try {
      await patchVideo(id, spec);
      const job = await renderVideo(id);
      setRender(job);
      pollRef.current = setInterval(async () => {
        const r = await getRender(job.id);
        setRender(r);
        if (r.status === "done" || r.status === "error") {
          if (pollRef.current) clearInterval(pollRef.current);
          setRendering(false);
        }
      }, 2000);
    } catch (e) {
      setError(String(e));
      setRendering(false);
    }
  }

  function seekTo(seconds: number) {
    const v = videoRef.current;
    if (v) v.currentTime = Math.max(0, Math.min(seconds, dur || seconds));
  }
  function playFrom(seconds: number) {
    seekTo(seconds);
    void videoRef.current?.play();
  }
  function togglePlay() {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) void v.play();
    else v.pause();
  }
  function fullscreen() {
    void frameRef.current?.requestFullscreen?.();
  }

  const activeIdx = spec
    ? spec.segments.findIndex(
        (s) =>
          cur * 1000 >= s.source_start_ms &&
          cur * 1000 < Math.max(s.source_end_ms, s.source_start_ms + 300),
      )
    : -1;

  useEffect(() => {
    if (playing && tab === "Script") activeRef.current?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIdx, playing, tab]);

  if (!spec) {
    return (
      <main className="mx-auto max-w-4xl px-6 py-12">
        <Link href={`/projects/${id}`} className="btn btn-ghost btn-sm -ml-2">
          ← Project
        </Link>
        <div className="card mt-6 p-6 text-sm text-[var(--text-2)]">
          {error ?? "No video yet — process a capture into a Workflow Graph first."}
        </div>
      </main>
    );
  }

  const activeSeg = activeIdx >= 0 ? spec.segments[activeIdx] : null;
  const zoomOn = !!activeSeg?.zoom.enabled && (playing || tab === "Zoom");
  const zoomSpeed = activeSeg?.zoom.speed ?? 3;
  const zoomStyle: React.CSSProperties = {
    transform: zoomOn ? `scale(${activeSeg!.zoom.scale})` : "scale(1)",
    transformOrigin: activeSeg ? `${activeSeg.zoom.cx * 100}% ${activeSeg.zoom.cy * 100}%` : "center",
    transition: `transform ${((6 - zoomSpeed) * 0.3).toFixed(2)}s ease`,
  };
  const captionText = spec.captions.enabled && activeSeg ? eff(activeSeg) : "";

  const totalMs =
    (dur ? dur * 1000 : 0) ||
    spec.segments.reduce((m, s) => Math.max(m, s.source_end_ms || 0), 0) ||
    1;
  const query = q.trim().toLowerCase();

  const CHIPS: { key: Tab | "trim" | "crop" | "soon" | "enhance"; label: string; icon: string; soon?: boolean }[] = [
    { key: "trim", label: "Trim", icon: "✂" },
    { key: "crop", label: "Crop", icon: "⛶" },
    { key: "soon", label: "Rotate", icon: "⟳", soon: true },
    { key: "soon", label: "Blur", icon: "◐", soon: true },
    { key: "Elements", label: "Elements", icon: "✦" },
    { key: "Captions", label: "Captions", icon: "CC" },
    { key: "enhance", label: "AI Enhance", icon: "✨" },
  ];

  return (
    <div className="flex h-screen flex-col bg-[var(--bg)] text-[var(--text)]">
      {/* Trim / Crop modal windows */}
      {activeTool === "trim" && source && (
        <TrimModal
          source={source}
          segments={spec.segments}
          onCancel={() => setActiveTool(null)}
          onSave={(segs) => {
            setSpec({ ...spec, segments: segs });
            setActiveTool(null);
          }}
        />
      )}
      {activeTool === "crop" && source && (
        <CropModal
          source={source}
          crop={spec.crop}
          onCancel={() => setActiveTool(null)}
          onSave={(crop) => {
            setSpec({ ...spec, crop });
            setActiveTool(null);
          }}
        />
      )}
      {/* header */}
      <header className="flex items-center justify-between gap-4 border-b border-[var(--border)] bg-[var(--card)] px-6 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <Link href={`/projects/${id}`} className="btn btn-ghost btn-sm -ml-1" title="Back">
            ←
          </Link>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="truncate text-[17px] font-semibold tracking-tight">{spec.title}</h1>
              <Link
                href={`/projects/${id}/document`}
                className="rounded-lg px-2 py-0.5 text-xs font-medium text-[var(--text-2)] hover:bg-[var(--hover)]"
              >
                Document
              </Link>
            </div>
            <div className="text-[11px] text-[var(--text-3)]">
              {saving ? "Saving…" : dirty ? "Unsaved changes" : "Saved just now"}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {!dirty && <span className="hidden text-xs text-[var(--text-3)] sm:inline">Saved</span>}
          <ShareButton projectId={id} kind="video" />
          <button onClick={doRender} disabled={rendering} className="btn btn-primary btn-sm">
            {rendering ? (
              <>
                <Spinner /> Generating…
              </>
            ) : (
              "Generate Video"
            )}
          </button>
        </div>
      </header>

      {error && (
        <p className="mx-6 mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
          {error}
        </p>
      )}

      {/* body: 35% script / 65% preview */}
      <div className="flex min-h-0 flex-1">
        {/* LEFT — script / tools */}
        <aside className="flex w-[35%] min-w-[340px] max-w-[560px] flex-col border-r border-[var(--border)] bg-[var(--card)]">
          <nav className="flex items-center gap-1 border-b border-[var(--border)] px-3 py-2">
            {SIDE_TABS.map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                  tab === t ? "bg-[#6d5dfb]/10 text-[#6d5dfb]" : "text-[var(--text-2)] hover:bg-[var(--hover)]"
                }`}
              >
                {t}
              </button>
            ))}
            {TOOL_TABS.includes(tab) && (
              <span className="ml-auto flex items-center gap-2 text-xs text-[var(--text-2)]">
                {tab}
                <button onClick={() => setTab("Script")} className="btn btn-ghost btn-sm">
                  Done
                </button>
              </span>
            )}
          </nav>

          <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
            {tab === "Script" && (
              <>
                {dirty && (
                  <div className="sticky top-0 z-10 -mx-4 -mt-4 mb-3 flex items-center gap-2 border-b border-[var(--border)] bg-[var(--card)] px-4 py-2.5">
                    <span className="text-xs font-medium text-amber-500">Unsaved edits</span>
                    <div className="ml-auto flex items-center gap-2">
                      <button onClick={discard} disabled={saving} className="btn btn-ghost btn-sm">
                        Discard
                      </button>
                      <button onClick={save} disabled={saving} className="btn btn-secondary btn-sm">
                        {saving ? "Saving…" : "Keep changes"}
                      </button>
                      {!useOriginal && (
                        <button
                          onClick={refreshVoice}
                          disabled={saving || voiceLoading}
                          className="btn btn-primary btn-sm"
                        >
                          {voiceLoading ? (
                            <>
                              <Spinner /> Voice…
                            </>
                          ) : (
                            "↻ Refresh voice"
                          )}
                        </button>
                      )}
                    </div>
                  </div>
                )}
                <div className="space-y-2">
                  <div className="relative">
                    <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-3)]">
                      ⌕
                    </span>
                    <input
                      value={q}
                      onChange={(e) => setQ(e.target.value)}
                      placeholder="Search script…"
                      className="input pl-8"
                    />
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      value={tone}
                      onChange={(e) => setTone(e.target.value as Tone)}
                      title="Tone for AI writing"
                      className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 py-1.5 text-xs text-[var(--text-2)]"
                    >
                      {TONES.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => rewriteAll()}
                      disabled={rewriting !== null}
                      title={`Rewrite the whole script (${tone})`}
                      className="btn btn-secondary btn-sm whitespace-nowrap"
                    >
                      {rewriting === "all" ? (
                        <>
                          <Spinner /> Rewriting…
                        </>
                      ) : (
                        "✨ AI Rewrite"
                      )}
                    </button>
                    <button
                      onClick={() => genScript(true)}
                      disabled={rewriting !== null}
                      title="Write narration for scenes that have none"
                      className="btn btn-secondary btn-sm whitespace-nowrap"
                    >
                      {rewriting === "gen" ? (
                        <>
                          <Spinner /> Writing…
                        </>
                      ) : (
                        "✍ Generate"
                      )}
                    </button>
                  </div>
                </div>

                {spec.segments.map((seg, i) => {
                  const text = eff(seg);
                  if (query && !text.toLowerCase().includes(query)) return null;
                  return (
                    <div
                      key={seg.step_id}
                      ref={activeIdx === i ? activeRef : null}
                      className={`group rounded-xl border px-3 py-2.5 transition-colors ${
                        activeIdx === i
                          ? "border-[#6d5dfb]/30 bg-[#6d5dfb]/5"
                          : "border-transparent hover:bg-[var(--hover)]"
                      }`}
                    >
                      <div className="mb-1 flex items-center gap-2">
                        <button
                          onClick={() => playFrom(seg.source_start_ms / 1000)}
                          className="font-mono text-xs font-medium text-[#6d5dfb]"
                          title="Play from here"
                        >
                          {mmss(seg.source_start_ms / 1000)}
                        </button>
                        {seg.dirty && (
                          <span className="badge bg-amber-100 text-amber-700">edited</span>
                        )}
                        <div className="ml-auto flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                          <IconBtn title="Edit" onClick={() => setEditIdx(editIdx === i ? null : i)}>
                            ✏
                          </IconBtn>
                          <IconBtn title="Voice" onClick={() => setTab("AI Voice")}>
                            🎤
                          </IconBtn>
                          <IconBtn
                            title="AI Rewrite this line"
                            onClick={() => rewriteOne(i)}
                            disabled={rewriting !== null}
                          >
                            {rewriting === i ? "…" : "⚡"}
                          </IconBtn>
                          <IconBtn title="Delete" onClick={() => deleteSegment(i)} danger>
                            🗑
                          </IconBtn>
                        </div>
                      </div>
                      {editIdx === i ? (
                        <textarea
                          autoFocus
                          defaultValue={text}
                          onBlur={(e) => {
                            setSegText(i, e.target.value);
                            setEditIdx(null);
                          }}
                          placeholder="Type the narration…"
                          className="input min-h-[64px] w-full resize-y text-sm leading-relaxed"
                        />
                      ) : seg.words.length ? (
                        <p className="text-[15px] leading-relaxed text-[var(--text)]">
                          {seg.words.map((w, wi) => {
                            const struck = seg.removed.includes(wi);
                            return (
                              <button
                                key={wi}
                                onClick={(e) => {
                                  if (e.shiftKey) {
                                    mutateSeg(i, {
                                      removed: struck
                                        ? seg.removed.filter((x) => x !== wi)
                                        : [...seg.removed, wi],
                                    });
                                  } else {
                                    playFrom(wordTimeSec(seg, wi));
                                  }
                                }}
                                title="click to play · shift-click to strike"
                                className={`mr-1 rounded px-0.5 ${
                                  struck ? "text-[#c4c9d6] line-through" : "hover:bg-[#6d5dfb]/10"
                                }`}
                              >
                                {w}
                              </button>
                            );
                          })}
                        </p>
                      ) : (
                        <p
                          className="cursor-text text-sm italic text-[var(--text-3)]"
                          onClick={() => setEditIdx(i)}
                        >
                          Empty — click ✏ to add narration.
                        </p>
                      )}
                    </div>
                  );
                })}

                <button
                  onClick={addSegment}
                  className="w-full rounded-xl border border-dashed border-[var(--border-strong)] py-2 text-sm font-medium text-[#6d5dfb] hover:bg-[#6d5dfb]/5"
                >
                  + Add paragraph
                </button>
              </>
            )}

            {tab === "AI Voice" && (
              <div className="space-y-3">
                <VoicePanel
                  value={spec.voice}
                  onChange={(patch) => setSpec({ ...spec, voice: { ...spec.voice, ...patch } })}
                />
                {!useOriginal && (
                  <button
                    onClick={refreshVoice}
                    disabled={voiceLoading || saving}
                    className={`btn btn-sm w-full ${dirty ? "btn-primary" : "btn-secondary"}`}
                  >
                    {voiceLoading ? (
                      <>
                        <Spinner /> Refreshing…
                      </>
                    ) : (
                      "↻ Refresh voice"
                    )}
                  </button>
                )}
              </div>
            )}

            {tab === "Zoom" && (
              <ZoomPanel
                spec={spec}
                zoomIdx={zoomIdx}
                setZoomIdx={setZoomIdx}
                activeIdx={activeIdx}
                mutateSeg={mutateSeg}
                patchSpec={patchSpec}
                seekTo={seekTo}
                onSuggest={aiZooms}
                suggesting={zoomBusy}
              />
            )}

            {tab === "Elements" && (
              <ElementsPanel
                spec={spec}
                selEl={selEl}
                setSelEl={setSelEl}
                addElement={addElement}
                updateElement={updateElement}
                deleteElement={deleteElement}
                dur={dur}
                cur={cur}
              />
            )}
          </div>
        </aside>

        {/* RIGHT — preview */}
        <main className="flex min-w-0 flex-1 flex-col overflow-hidden p-4">
          {showRender && render ? (
            <div className="mx-auto w-full max-w-3xl">
              <div className="mb-2 flex items-center gap-2 text-sm">
                <span className="text-[var(--text-2)]">Generated video</span>
                <span
                  className={`badge ${
                    render.status === "done"
                      ? "bg-emerald-100 text-emerald-700"
                      : render.status === "error"
                        ? "bg-red-100 text-red-700"
                        : "bg-amber-100 text-amber-700"
                  }`}
                >
                  {render.status}
                </span>
                <button onClick={() => setShowRender(false)} className="btn btn-ghost btn-sm ml-auto">
                  ← back to preview
                </button>
              </div>
              {render.status === "done" && render.output_url ? (
                <video src={render.output_url} controls className="w-full rounded-2xl bg-black shadow-sm" />
              ) : (
                <div className="flex items-center justify-center gap-2 rounded-2xl border border-[var(--border)] bg-[var(--card)] py-24 text-sm text-[var(--text-2)]">
                  {render.status === "error" ? (
                    <span className="text-red-600">{JSON.stringify(render.error_json)}</span>
                  ) : (
                    <>
                      <Spinner /> Rendering…
                    </>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div className="mx-auto flex min-h-0 w-full max-w-4xl flex-1 flex-col">
              {/* preview */}
              <div className="flex min-h-0 flex-1 items-center justify-center">
                {source ? (
                  <div
                    ref={frameRef}
                    className="relative flex max-h-full overflow-hidden rounded-2xl bg-black shadow-lg"
                  >
                    <video
                      ref={videoRef}
                      src={mediaUrl(source)}
                      className="max-h-full w-auto"
                      style={zoomStyle}
                      onLoadedMetadata={(e) => {
                        setDur(e.currentTarget.duration || 0);
                        e.currentTarget.muted = wantAiVoice;
                        e.currentTarget.playbackRate = rate;
                      }}
                      onTimeUpdate={(e) => {
                        const v = e.currentTarget;
                        setCur(v.currentTime);
                        const tr = spec.trim;
                        if (tr?.enabled && tr.end_ms > tr.start_ms && v.currentTime * 1000 >= tr.end_ms) {
                          v.pause();
                          v.currentTime = tr.start_ms / 1000;
                        }
                      }}
                      onPlay={(e) => {
                        setPlaying(true);
                        e.currentTarget.muted = wantAiVoice;
                        if (aiVoiceActive && audioRef.current) {
                          audioRef.current.currentTime = e.currentTarget.currentTime;
                          void audioRef.current.play().catch(() => {});
                        }
                      }}
                      onPause={() => {
                        setPlaying(false);
                        audioRef.current?.pause();
                      }}
                      onSeeked={(e) => {
                        if (aiVoiceActive && audioRef.current)
                          audioRef.current.currentTime = e.currentTarget.currentTime;
                      }}
                    />
                    <audio ref={audioRef} src={voiceUrl ?? undefined} preload="auto" />
                    {captionText && (
                      <div className="pointer-events-none absolute inset-x-0 bottom-4 flex justify-center px-6">
                        <span className="max-w-[90%] rounded-lg bg-black/75 px-3 py-1.5 text-center text-sm text-[var(--text)]">
                          {captionText}
                        </span>
                      </div>
                    )}
                    <PreviewOverlay
                      frame={frameSize}
                      tab={tab}
                      spec={spec}
                      setSpec={setSpec}
                      selId={selEl}
                      setSelId={setSelEl}
                      curMs={cur * 1000}
                    />
                  </div>
                ) : (
                  <div className="flex aspect-video w-full items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--card)] text-sm text-[var(--text-3)]">
                    No source video for this project
                  </div>
                )}
              </div>

              {/* playback controls */}
              <div className="mt-3 flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-2.5">
                <button
                  onClick={togglePlay}
                  className="flex h-9 w-9 items-center justify-center rounded-full bg-[#6d5dfb] text-white shadow-sm"
                >
                  {playing ? "❚❚" : "▶"}
                </button>
                <button
                  onClick={() => {
                    if (videoRef.current) videoRef.current.muted = !videoRef.current.muted;
                  }}
                  className="btn btn-ghost btn-sm"
                  title="Mute / unmute"
                >
                  🔊
                </button>
                <span className="font-mono text-xs text-[var(--text-2)]">
                  {clock(cur)} / {clock(dur)}
                </span>
                <input
                  type="range"
                  min={0}
                  max={dur || 1}
                  step={0.05}
                  value={cur}
                  onChange={(e) => seekTo(Number(e.target.value))}
                  className="flex-1 accent-[#6d5dfb]"
                />
                <select
                  value={rate}
                  onChange={(e) => setRate(Number(e.target.value))}
                  className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-xs"
                >
                  {[0.5, 1, 1.5, 2].map((r) => (
                    <option key={r} value={r}>
                      {r}x
                    </option>
                  ))}
                </select>
                <button onClick={fullscreen} className="btn btn-ghost btn-sm" title="Fullscreen">
                  ⛶
                </button>
              </div>

              <p className="mt-2 flex items-center justify-center gap-1.5 text-center text-[11px] text-[var(--text-3)]">
                {voiceLoading ? (
                  <>
                    <Spinner /> Preparing the AI voice…
                  </>
                ) : voiceError ? (
                  <span className="text-amber-600">
                    ⚠ Couldn’t build the AI voice preview — is the worker running?
                  </span>
                ) : aiVoiceActive ? (
                  <>
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Preview plays the AI
                    voice — Generate for exact timing.
                  </>
                ) : useOriginal ? (
                  "Preview uses your original recorded voice."
                ) : (
                  "Live preview — zoom, crop guide & elements simulate the final render."
                )}
              </p>
            </div>
          )}
        </main>
      </div>

      {/* tool chips — above the timeline */}
      <div className="flex flex-wrap items-center gap-2 border-t border-[var(--border)] bg-[var(--card)] px-6 py-2.5">
        {CHIPS.map((c, i) => {
          const active =
            (c.key === "Elements" && tab === "Elements") ||
            (c.key === "trim" && activeTool === "trim") ||
            (c.key === "crop" && activeTool === "crop");
          const capOn = c.label === "Captions" && spec.captions.enabled;
          const busy = c.key === "enhance" && rewriting === "enhance";
          return (
            <button
              key={i}
              disabled={c.soon || (c.key === "enhance" && rewriting !== null)}
              title={c.soon ? "Coming soon" : c.key === "enhance" ? "Tighten the whole script with AI" : c.label}
              onClick={() => {
                if (c.soon) return;
                if (c.key === "enhance") void enhance();
                else if (c.key === "Captions") setSpec({ ...spec, captions: { enabled: !spec.captions.enabled } });
                else if (c.key === "trim") {
                  videoRef.current?.pause();
                  setActiveTool("trim");
                } else if (c.key === "crop") {
                  videoRef.current?.pause();
                  setActiveTool("crop");
                } else setTab(c.key as Tab);
              }}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-all ${
                active || capOn
                  ? "border-[#6d5dfb] bg-[#6d5dfb]/10 text-[#6d5dfb]"
                  : "border-[var(--border)] bg-[var(--bg)] text-[var(--text-2)] hover:bg-[var(--hover)]"
              } ${c.soon ? "opacity-40" : ""}`}
            >
              {busy ? <Spinner /> : <span className="text-[13px]">{c.icon}</span>}
              {c.label}
            </button>
          );
        })}
      </div>

      {/* TIMELINE */}
      <TimelineTracks
        spec={spec}
        totalMs={totalMs}
        cur={cur}
        dur={dur}
        activeIdx={activeIdx}
        useOriginal={!!useOriginal}
        tlZoom={tlZoom}
        setTlZoom={setTlZoom}
        seekTo={seekTo}
        onMove={moveSegment}
        onResize={resizeSegment}
        onDelete={() => activeIdx >= 0 && deleteSegment(activeIdx)}
        onDuplicate={() => activeIdx >= 0 && duplicateSegment(activeIdx)}
        onSplit={() => activeIdx >= 0 && splitSegment(activeIdx, cur * 1000)}
        onUndo={undo}
        onRedo={redo}
        canUndo={histState.canUndo}
        canRedo={histState.canRedo}
      />
    </div>
  );
}

/* ---------------- small building blocks ---------------- */

function IconBtn({
  children,
  onClick,
  title,
  danger,
  disabled,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  title?: string;
  danger?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`rounded-md px-1.5 py-1 text-xs transition-colors disabled:opacity-40 ${
        danger ? "text-[var(--text-3)] hover:bg-red-50 hover:text-red-500" : "text-[var(--text-2)] hover:bg-[var(--hover)]"
      }`}
    >
      {children}
    </button>
  );
}

function ZoomPanel({
  spec,
  zoomIdx,
  setZoomIdx,
  activeIdx,
  mutateSeg,
  patchSpec,
  seekTo,
  onSuggest,
  suggesting,
}: {
  spec: EditSpec;
  zoomIdx: number | null;
  setZoomIdx: (n: number) => void;
  activeIdx: number;
  mutateSeg: (i: number, p: Partial<EditSegment>) => void;
  patchSpec: (p: Partial<EditSpec>) => void;
  seekTo: (s: number) => void;
  onSuggest: () => void;
  suggesting: boolean;
}) {
  const motionZoom = spec.motion_zoom ?? true;
  const zi = zoomIdx ?? (activeIdx >= 0 ? activeIdx : 0);
  const seg = spec.segments[zi];
  if (!seg) return <p className="text-sm text-[var(--text-3)]">No scenes to zoom.</p>;
  const z = seg.zoom;
  const setZoom = (patch: Partial<EditSegment["zoom"]>) => mutateSeg(zi, { zoom: { ...z, ...patch } });
  const pickPos = (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setZoom({
      enabled: true,
      cx: Number(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)).toFixed(3)),
      cy: Number(Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)).toFixed(3)),
    });
  };
  const level = Math.round(z.scale * 100);
  const speed = z.speed ?? 3;
  return (
    <div className="space-y-5">
      <label className="flex cursor-pointer items-start justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] p-3">
        <span>
          <span className="text-sm font-medium">Auto-zoom on mouse clicks</span>
          <span className="mt-0.5 block text-xs text-[var(--text-2)]">
            Track cursor/click activity and zoom toward it on scenes without a manual zoom.
          </span>
        </span>
        <input
          type="checkbox"
          checked={motionZoom}
          onChange={(e) => patchSpec({ motion_zoom: e.target.checked })}
          className="mt-0.5 h-4 w-8 flex-none accent-[#6d5dfb]"
        />
      </label>
      <button
        onClick={onSuggest}
        disabled={suggesting}
        title="Let AI pick which scenes to zoom and how much"
        className="btn btn-secondary btn-sm w-full"
      >
        {suggesting ? (
          <>
            <Spinner /> Analyzing scenes…
          </>
        ) : (
          "✨ Suggest zooms with AI"
        )}
      </button>
      <div>
        <div className="label mb-1">Scene</div>
        <select
          value={zi}
          onChange={(e) => {
            const i = Number(e.target.value);
            setZoomIdx(i);
            seekTo(spec.segments[i].source_start_ms / 1000);
          }}
          className="input"
        >
          {spec.segments.map((s, i) => (
            <option key={s.step_id} value={i}>
              {i + 1}. {mmss(s.source_start_ms / 1000)} · {s.target ?? "Scene"}
            </option>
          ))}
        </select>
      </div>
      <label className="flex items-center justify-between">
        <span className="text-sm font-medium">Add zoom effects</span>
        <input
          type="checkbox"
          checked={z.enabled}
          onChange={(e) => setZoom({ enabled: e.target.checked })}
          className="h-4 w-8 accent-[#6d5dfb]"
        />
      </label>
      <div>
        <div className="label mb-1.5">Select zoom position</div>
        <div
          onPointerDown={(e) => {
            e.currentTarget.setPointerCapture(e.pointerId);
            pickPos(e);
          }}
          onPointerMove={(e) => e.buttons === 1 && pickPos(e)}
          className="relative grid aspect-video w-full cursor-crosshair grid-cols-6 grid-rows-4 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--bg)]"
        >
          {Array.from({ length: 24 }).map((_, i) => (
            <div key={i} className="border border-[var(--border)]/70" />
          ))}
          <span
            style={{ left: `${z.cx * 100}%`, top: `${z.cy * 100}%` }}
            className="pointer-events-none absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#6d5dfb] shadow ring-2 ring-white"
          />
        </div>
      </div>
      {(
        [
          ["Select zoom level", level, 100, 250, 5, (v: number) => setZoom({ enabled: true, scale: v / 100 })],
          ["Select zoom speed", speed, 1, 5, 1, (v: number) => setZoom({ speed: v })],
        ] as const
      ).map(([label, val, min, max, step, on]) => (
        <div key={label}>
          <div className="mb-1 flex items-center justify-between">
            <span className="label">{label}</span>
            <span className="rounded border border-[var(--border)] px-1.5 text-xs">{val}</span>
          </div>
          <input
            type="range"
            min={min}
            max={max}
            step={step}
            value={val}
            onChange={(e) => on(Number(e.target.value))}
            className="w-full accent-[#6d5dfb]"
          />
        </div>
      ))}
      <button onClick={() => setZoom({ enabled: false })} className="btn btn-secondary btn-sm w-full">
        🗑 Delete zoom
      </button>
    </div>
  );
}

function ElementsPanel({
  spec,
  selEl,
  setSelEl,
  addElement,
  updateElement,
  deleteElement,
  dur,
  cur,
}: {
  spec: EditSpec;
  selEl: string | null;
  setSelEl: (id: string | null) => void;
  addElement: (t: EditElement["type"]) => void;
  updateElement: (id: string, p: Partial<EditElement>) => void;
  deleteElement: (id: string) => void;
  dur: number;
  cur: number;
}) {
  const els = spec.elements ?? [];
  const sel = els.find((e) => e.id === selEl) ?? null;
  return (
    <div className="space-y-4">
      <p className="text-xs text-[var(--text-3)]">Add text or a highlight box, then drag/resize it on the preview.</p>
      <div className="flex gap-2">
        <button onClick={() => addElement("text")} className="btn btn-secondary btn-sm">
          + Text
        </button>
        <button onClick={() => addElement("box")} className="btn btn-secondary btn-sm">
          + Highlight box
        </button>
      </div>
      {els.length === 0 && <p className="text-xs text-[var(--text-3)]">No elements yet.</p>}
      <div className="space-y-1.5">
        {els.map((el) => (
          <button
            key={el.id}
            onClick={() => setSelEl(el.id)}
            className={`flex w-full items-center gap-2 rounded-xl border px-3 py-2 text-left text-sm ${
              selEl === el.id ? "border-[#6d5dfb]/40 bg-[#6d5dfb]/5" : "border-[var(--border)] hover:bg-[var(--hover)]"
            }`}
          >
            <span className="text-xs uppercase text-[var(--text-3)]">{el.type}</span>
            <span className="truncate">{el.type === "text" ? el.text || "Text" : "Highlight"}</span>
          </button>
        ))}
      </div>
      {sel && (
        <div className="space-y-3 rounded-xl border border-[var(--border)] p-3">
          {sel.type === "text" && (
            <div>
              <div className="label mb-1">Text</div>
              <input value={sel.text ?? ""} onChange={(e) => updateElement(sel.id, { text: e.target.value })} className="input" />
            </div>
          )}
          <div className="flex items-center gap-3">
            <span className="label">Color</span>
            <input
              type="color"
              value={sel.color ?? (sel.type === "box" ? "#6d5dfb" : "#111827")}
              onChange={(e) => updateElement(sel.id, { color: e.target.value })}
              className="h-7 w-10 rounded border border-[var(--border)] bg-transparent"
            />
            <button onClick={() => deleteElement(sel.id)} className="btn btn-ghost btn-sm ml-auto text-red-500">
              🗑 Delete
            </button>
          </div>
          <div className="border-t border-[var(--border)] pt-3">
            <label className="flex items-center justify-between">
              <span className="text-sm">Show only for a time range</span>
              <input
                type="checkbox"
                checked={(sel.end_ms ?? 0) > (sel.start_ms ?? 0)}
                onChange={(e) =>
                  updateElement(
                    sel.id,
                    e.target.checked
                      ? { start_ms: Math.round(cur * 1000), end_ms: Math.round(Math.min(dur, cur + 5) * 1000) }
                      : { start_ms: 0, end_ms: 0 },
                  )
                }
                className="h-4 w-8 accent-[#6d5dfb]"
              />
            </label>
            {(sel.end_ms ?? 0) > (sel.start_ms ?? 0) && (
              <div className="mt-2 space-y-2">
                {(["From", "To"] as const).map((which) => {
                  const val = which === "From" ? sel.start_ms ?? 0 : sel.end_ms ?? 0;
                  return (
                    <div key={which} className="flex items-center gap-2">
                      <span className="w-9 text-xs text-[var(--text-3)]">{which}</span>
                      <input
                        type="range"
                        min={0}
                        max={(dur || 1) * 1000}
                        step={100}
                        value={val}
                        onChange={(e) => {
                          const v = Number(e.target.value);
                          updateElement(
                            sel.id,
                            which === "From"
                              ? { start_ms: Math.min(v, (sel.end_ms ?? 0) - 200) }
                              : { end_ms: Math.max(v, (sel.start_ms ?? 0) + 200) },
                          );
                        }}
                        className="flex-1 accent-[#6d5dfb]"
                      />
                      <span className="w-11 text-right font-mono text-xs text-[var(--text-2)]">{mmss(val / 1000)}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function TimelineTracks({
  spec,
  totalMs,
  cur,
  dur,
  activeIdx,
  useOriginal,
  tlZoom,
  setTlZoom,
  seekTo,
  onMove,
  onResize,
  onDelete,
  onDuplicate,
  onSplit,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
}: {
  spec: EditSpec;
  totalMs: number;
  cur: number;
  dur: number;
  activeIdx: number;
  useOriginal: boolean;
  tlZoom: number;
  setTlZoom: (n: number) => void;
  seekTo: (s: number) => void;
  onMove: (i: number, startMs: number) => void;
  onResize: (i: number, endMs: number) => void;
  onDelete: () => void;
  onDuplicate: () => void;
  onSplit: () => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}) {
  const blocks = spec.segments.map((s, i) => {
    const left = (s.source_start_ms / totalMs) * 100;
    const width = Math.max(
      1.5,
      ((Math.max(s.source_end_ms, s.source_start_ms + 400) - s.source_start_ms) / totalMs) * 100,
    );
    return { s, i, left, width, text: eff(s) };
  });
  const ROWS: { label: string; render: () => React.ReactNode }[] = [
    {
      label: "Video",
      render: () =>
        blocks.map((b) => (
          <DraggableBlock
            key={b.s.step_id}
            b={b}
            totalMs={totalMs}
            active={activeIdx === b.i}
            onSeek={() => seekTo(b.s.source_start_ms / 1000)}
            onMove={(startMs) => onMove(b.i, startMs)}
            onResize={(endMs) => onResize(b.i, endMs)}
          />
        )),
    },
    {
      label: "Audio",
      render: () => (
        <div className="absolute inset-x-1 top-1/2 h-6 -translate-y-1/2">
          <div className="flex h-full items-center gap-[2px] overflow-hidden opacity-70">
            {Array.from({ length: 120 }).map((_, i) => (
              <span
                key={i}
                className="w-[2px] rounded bg-[var(--brand-2)]"
                style={{ height: `${20 + Math.abs(Math.sin(i * 1.7)) * 70}%` }}
              />
            ))}
          </div>
        </div>
      ),
    },
    {
      label: "Voice",
      render: () =>
        useOriginal
          ? null
          : blocks.map((b) => (
              <TlBlock key={b.s.step_id} b={b} active={false} onClick={() => seekTo(b.s.source_start_ms / 1000)} tone="voice" />
            )),
    },
    {
      label: "Captions",
      render: () =>
        spec.captions.enabled
          ? blocks.map((b) => (
              <TlBlock key={b.s.step_id} b={b} active={false} onClick={() => seekTo(b.s.source_start_ms / 1000)} tone="cap" label={b.text} />
            ))
          : null,
    },
    {
      label: "Zoom",
      render: () =>
        blocks
          .filter((b) => b.s.zoom.enabled)
          .map((b) => (
            <div
              key={b.s.step_id}
              onClick={() => seekTo(b.s.source_start_ms / 1000)}
              style={{ left: `${b.left}%` }}
              className="absolute top-1/2 flex h-5 w-5 -translate-x-1/2 -translate-y-1/2 cursor-pointer items-center justify-center rounded-full bg-amber-400/90 text-[10px] text-[var(--text)]"
              title="zoom"
            >
              ⛶
            </div>
          )),
    },
  ];

  return (
    <section className="border-t border-[var(--border)] bg-[var(--card)] px-6 py-3">
      {/* toolbar */}
      <div className="mb-2 flex items-center gap-1 text-[var(--text-2)]">
        <button onClick={onUndo} disabled={!canUndo} title="Undo (⌘Z)" className="btn btn-ghost btn-sm">
          ↶ Undo
        </button>
        <button onClick={onRedo} disabled={!canRedo} title="Redo (⌘⇧Z)" className="btn btn-ghost btn-sm">
          ↷ Redo
        </button>
        <button onClick={onSplit} className="btn btn-ghost btn-sm" title="Split scene at playhead">
          ✂ Split
        </button>
        <button onClick={onDuplicate} className="btn btn-ghost btn-sm" title="Duplicate scene">
          ⧉ Duplicate
        </button>
        <button onClick={onDelete} className="btn btn-ghost btn-sm" title="Delete scene">
          🗑 Delete
        </button>
        <div className="mx-2 h-4 w-px bg-[var(--border)]" />
        <span className="text-xs text-[var(--text-3)]" title="Snap (coming soon)">
          Snap
        </span>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-[var(--text-3)]">Zoom</span>
          <input
            type="range"
            min={1}
            max={4}
            step={0.5}
            value={tlZoom}
            onChange={(e) => setTlZoom(Number(e.target.value))}
            className="w-28 accent-[#6d5dfb]"
          />
          <button onClick={() => setTlZoom(1)} className="btn btn-ghost btn-sm">
            Fit
          </button>
        </div>
      </div>

      {/* ruler */}
      <div className="relative ml-20 h-4 overflow-hidden text-[10px] text-[var(--text-3)]">
        {Array.from({ length: 11 }).map((_, i) => (
          <span key={i} style={{ left: `${(i / 10) * 100}%` }} className="absolute -translate-x-1/2">
            {mmss(((totalMs / 1000) * i) / 10)}
          </span>
        ))}
      </div>

      {/* tracks */}
      <div className="max-h-56 space-y-1.5 overflow-y-auto pt-1">
        {ROWS.map((row) => (
          <div key={row.label} className="flex items-stretch gap-2">
            <div className="flex w-[72px] flex-none items-center text-xs font-medium text-[var(--text-2)]">
              {row.label}
            </div>
            <div className="relative h-10 flex-1 overflow-x-auto rounded-lg bg-[var(--bg)]">
              <div data-track className="relative h-full" style={{ width: `${tlZoom * 100}%`, minWidth: "100%" }}>
                {row.render()}
                {/* playhead */}
                {dur > 0 && (
                  <div
                    style={{ left: `${Math.min(100, (cur / (totalMs / 1000)) * 100)}%` }}
                    className="pointer-events-none absolute top-0 z-10 h-full w-0.5 bg-[#6d5dfb]"
                  />
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function DraggableBlock({
  b,
  totalMs,
  active,
  onSeek,
  onMove,
  onResize,
}: {
  b: { s: EditSegment; i: number; left: number; width: number; text: string };
  totalMs: number;
  active: boolean;
  onSeek: () => void;
  onMove: (startMs: number) => void;
  onResize: (endMs: number) => void;
}) {
  const drag = useRef<{ mode: "move" | "resize"; startX: number; orig: number; trackW: number; moved: boolean } | null>(
    null,
  );

  const begin = (mode: "move" | "resize") => (e: React.PointerEvent<HTMLElement>) => {
    e.stopPropagation();
    const track = e.currentTarget.closest("[data-track]") as HTMLElement | null;
    const trackW = track?.clientWidth || 1;
    drag.current = {
      mode,
      startX: e.clientX,
      orig: mode === "move" ? b.s.source_start_ms : b.s.source_end_ms,
      trackW,
      moved: false,
    };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };

  const move = (e: React.PointerEvent<HTMLElement>) => {
    const d = drag.current;
    if (!d) return;
    const deltaMs = ((e.clientX - d.startX) / d.trackW) * totalMs;
    if (Math.abs(e.clientX - d.startX) > 3) d.moved = true;
    const len = b.s.source_end_ms - b.s.source_start_ms;
    if (d.mode === "move") {
      onMove(Math.max(0, Math.min(d.orig + deltaMs, totalMs - len)));
    } else {
      onResize(Math.max(b.s.source_start_ms + 300, Math.min(d.orig + deltaMs, totalMs)));
    }
  };

  const end = () => {
    const d = drag.current;
    drag.current = null;
    if (d && !d.moved) onSeek(); // treat a non-drag as a click-to-seek
  };

  return (
    <div
      onPointerDown={begin("move")}
      onPointerMove={move}
      onPointerUp={end}
      style={{ left: `${b.left}%`, width: `${b.width}%` }}
      className={`absolute top-1/2 flex h-8 -translate-y-1/2 cursor-grab items-center overflow-hidden rounded-md bg-[#6d5dfb]/15 px-1.5 text-[10px] text-[#6d5dfb] ring-1 ring-[#6d5dfb]/25 active:cursor-grabbing ${
        active ? "ring-2 ring-[#6d5dfb]" : ""
      }`}
      title={b.text}
    >
      <span className="pointer-events-none truncate">{b.text}</span>
      <span
        onPointerDown={begin("resize")}
        onPointerMove={move}
        onPointerUp={end}
        className="absolute right-0 top-0 h-full w-2 cursor-ew-resize rounded-r-md bg-[#6d5dfb]/40"
        title="Resize"
      />
    </div>
  );
}

function TlBlock({
  b,
  active,
  onClick,
  tone,
  label,
}: {
  b: { left: number; width: number; text: string };
  active: boolean;
  onClick: () => void;
  tone: "video" | "voice" | "cap";
  label?: string;
}) {
  const tones = {
    video: "bg-[#6d5dfb]/15 text-[#6d5dfb] ring-[#6d5dfb]/25",
    voice: "bg-[var(--brand-2)]/15 text-[#6d5dfb] ring-[var(--brand-2)]/25",
    cap: "bg-emerald-500/10 text-emerald-700 ring-emerald-500/20",
  }[tone];
  return (
    <button
      onClick={onClick}
      style={{ left: `${b.left}%`, width: `${b.width}%` }}
      className={`absolute top-1/2 flex h-8 -translate-y-1/2 items-center overflow-hidden rounded-md px-1.5 text-[10px] ring-1 ${tones} ${
        active ? "ring-2 ring-[#6d5dfb]" : ""
      }`}
      title={label ?? b.text}
    >
      <span className="truncate">{label ?? b.text}</span>
    </button>
  );
}
