"use client";

import { use, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  activeCrop,
  cropList,
  downloadMedia,
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
  type CropRegion,
  type EditElement,
  type EditSegment,
  type EditSpec,
  type RenderJob,
} from "@/lib/api";
import { Spinner } from "@/components/ui";
import { VoicePanel } from "@/components/VoicePanel";
import { ShareButton } from "@/components/ShareButton";
import { PreviewOverlay } from "@/components/PreviewOverlay";
import { resolveDuration } from "@/components/EditModals";
import {
  Filmstrip,
  Waveform,
  useFilmstrip,
  useWaveform,
  type Frame,
} from "@/lib/media";

type Tone = "Professional" | "Casual" | "Energetic" | "Concise";
const TONES: Tone[] = ["Professional", "Casual", "Energetic", "Concise"];
const TONE_INSTR: Record<Tone, string> = {
  Professional: "Use a polished, professional, confident tone.",
  Casual: "Use a friendly, casual, conversational tone.",
  Energetic: "Use an upbeat, energetic, enthusiastic tone.",
  Concise: "Make each line as concise as possible while keeping the meaning.",
};
const DEFAULT_CROP: CropRegion = {
  enabled: true,
  x: 0.12,
  y: 0.12,
  w: 0.76,
  h: 0.76,
  start_ms: 0,
  end_ms: 0,
};
const ENHANCE_INSTR =
  "Tighten every line: remove filler, redundancy and hedging, fix awkward phrasing, and " +
  "make it crisp, natural to speak, and demo-ready. Keep all product and feature names.";

type Tab =
  | "Script"
  | "AI Voice"
  | "Zoom"
  | "Background"
  | "Intro"
  | "Trim"
  | "Crop"
  | "Elements"
  | "Captions";
const SIDE_TABS: Tab[] = ["Script", "AI Voice", "Zoom", "Background", "Intro"];
const TOOL_TABS: Tab[] = ["Elements"];

// Backdrop presets shared with the renderer (same ids in worker render.py).
const BG_PRESETS: { id: string; label: string; css: string }[] = [
  {
    id: "slate",
    label: "Slate",
    css: "linear-gradient(135deg,#0b0f1a,#1e2637)",
  },
  {
    id: "indigo",
    label: "Indigo",
    css: "linear-gradient(135deg,#6d5dfb,#a855f7)",
  },
  {
    id: "ocean",
    label: "Ocean",
    css: "linear-gradient(135deg,#0ea5e9,#6366f1)",
  },
  {
    id: "sunset",
    label: "Sunset",
    css: "linear-gradient(135deg,#f97316,#ec4899)",
  },
  {
    id: "forest",
    label: "Forest",
    css: "linear-gradient(135deg,#10b981,#0d9488)",
  },
  {
    id: "light",
    label: "Light",
    css: "linear-gradient(135deg,#e2e8f0,#f8fafc)",
  },
];

const eff = (s: EditSegment) =>
  s.words.filter((_, i) => !s.removed.includes(i)).join(" ");
const tokenize = (text: string) => text.trim().split(/\s+/).filter(Boolean);
const wordTimeSec = (s: EditSegment, wi: number) => {
  const start = s.source_start_ms;
  const end = Math.max(s.source_end_ms, start + 300);
  const n = Math.max(1, s.words.length);
  return (start + ((end - start) * wi) / n) / 1000;
};
const mmss = (t: number) =>
  `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const clock = (t: number) =>
  `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(Math.floor(t % 60)).padStart(2, "0")}.${String(
    Math.floor((t % 1) * 100),
  ).padStart(2, "0")}`;
// Slice the full-source waveform peaks down to the portion covering [a, b] source-ms.
const peaksInRange = (
  peaks: number[],
  durSec: number,
  a: number,
  b: number,
): number[] => {
  const total = durSec * 1000;
  if (!peaks.length || total <= 0) return [];
  const i0 = Math.max(0, Math.floor((a / total) * peaks.length));
  const i1 = Math.min(peaks.length, Math.ceil((b / total) * peaks.length));
  return peaks.slice(i0, i1);
};
// Real frames that fall inside [a, b] source-ms; a short block with no sampled
// frame gets its nearest neighbour so every block shows real footage.
const framesInRange = (frames: Frame[], a: number, b: number): Frame[] => {
  const inR = frames.filter((f) => f.t >= a - 1 && f.t <= b + 1);
  if (inR.length) return inR;
  const mid = (a + b) / 2;
  let nearest: Frame | null = null;
  for (const f of frames)
    if (!nearest || Math.abs(f.t - mid) < Math.abs(nearest.t - mid))
      nearest = f;
  return nearest ? [nearest] : [];
};

export default function VideoEditor({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
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
  const [rewriting, setRewriting] = useState<
    null | "all" | "enhance" | "gen" | number
  >(null);
  const [tone, setTone] = useState<Tone>("Professional");
  const [zoomBusy, setZoomBusy] = useState(false);
  const [activeTool, setActiveTool] = useState<null | "trim" | "crop">(null); // inline preview tools
  const [cropSel, setCropSel] = useState(0); // which crop region is being edited
  const timelineRef = useRef<HTMLElement>(null);

  // undo / redo history (coalesced snapshots of the whole edit-spec)
  const past = useRef<EditSpec[]>([]);
  const future = useRef<EditSpec[]>([]);
  const baseline = useRef<EditSpec | null>(null);
  const skipHist = useRef(false);
  const [histState, setHistState] = useState({
    canUndo: false,
    canRedo: false,
  });
  const refreshHist = useCallback(
    () =>
      setHistState({
        canUndo: past.current.length > 0,
        canRedo: future.current.length > 0,
      }),
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
  const dirty =
    !!spec && !!savedSpec && JSON.stringify(spec) !== JSON.stringify(savedSpec);

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
          const { url, ready } = await pollVoiceTrack(
            id,
            voiceKey!,
            voiceSpeed!,
          );
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
      if (
        baseline.current &&
        JSON.stringify(baseline.current) !== JSON.stringify(spec)
      ) {
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
      s
        ? {
            ...s,
            segments: s.segments.map((seg, i) =>
              i === idx ? { ...seg, ...patch } : seg,
            ),
          }
        : s,
    );
  }, []);

  const patchSpec = useCallback((patch: Partial<EditSpec>) => {
    setSpec((s) => (s ? { ...s, ...patch } : s));
  }, []);

  const setSegText = useCallback(
    (idx: number, text: string) =>
      mutateSeg(idx, { words: tokenize(text), removed: [] }),
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
    setSpec((s) =>
      s ? { ...s, segments: s.segments.filter((_, i) => i !== idx) } : s,
    );
  }, []);

  // Skip a scene: it stays in place on the timeline (greyed) but is jumped over
  // on playback and excluded from the render — distinct from deleting it.
  const toggleSkip = useCallback((idx: number) => {
    setSpec((s) =>
      s
        ? {
            ...s,
            segments: s.segments.map((seg, i) =>
              i === idx ? { ...seg, skipped: !seg.skipped } : seg,
            ),
          }
        : s,
    );
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
          i === idx
            ? { ...g, source_start_ms: start, source_end_ms: start + len }
            : g,
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
        segments: s.segments.map((g, i) =>
          i === idx ? { ...g, source_end_ms: end } : g,
        ),
      };
    });
  }, []);
  const resizeSegmentStart = useCallback((idx: number, startMs: number) => {
    setSpec((s) => {
      if (!s || !s.segments[idx]) return s;
      const seg = s.segments[idx];
      const start = Math.round(
        Math.max(0, Math.min(startMs, seg.source_end_ms - 300)),
      );
      return {
        ...s,
        segments: s.segments.map((g, i) =>
          i === idx ? { ...g, source_start_ms: start } : g,
        ),
      };
    });
  }, []);

  // Trim mode (compressed, gap-free timeline): a boundary sits between two
  // time-adjacent clips (or at the very start/end, where one side is absent).
  // Dragging it moves both sides together so clips always stay touching —
  // matching the old Trim popup's "coupled" edge-drag behavior.
  const moveBoundary = useCallback(
    (leftIdx: number | null, rightIdx: number | null, ms: number) => {
      setSpec((s) => {
        if (!s) return s;
        const MIN = 120;
        const segs = [...s.segments];
        const left = leftIdx != null ? segs[leftIdx] : null;
        const right = rightIdx != null ? segs[rightIdx] : null;
        const lo = left ? left.source_start_ms + MIN : 0;
        const hi = right ? right.source_end_ms - MIN : Infinity;
        const at = Math.round(Math.max(lo, Math.min(ms, hi)));
        if (left && leftIdx != null)
          segs[leftIdx] = { ...left, source_end_ms: at };
        if (right && rightIdx != null)
          segs[rightIdx] = { ...right, source_start_ms: at };
        return { ...s, segments: segs };
      });
    },
    [],
  );

  // On drag release, re-split the two clips' words proportionally to their new
  // durations so captions/voice stay aligned with the moved boundary.
  const finalizeBoundary = useCallback(
    (leftIdx: number | null, rightIdx: number | null) => {
      if (leftIdx == null || rightIdx == null) return;
      setSpec((s) => {
        if (!s) return s;
        const A = s.segments[leftIdx];
        const B = s.segments[rightIdx];
        if (!A || !B) return s;
        const words = [...A.words, ...B.words];
        const removed = [
          ...A.removed,
          ...B.removed.map((r) => r + A.words.length),
        ];
        const durA = Math.max(0, A.source_end_ms - A.source_start_ms);
        const durB = Math.max(0, B.source_end_ms - B.source_start_ms);
        const frac = durA / Math.max(1, durA + durB);
        const wi = Math.round(words.length * frac);
        const segs = [...s.segments];
        segs[leftIdx] = {
          ...A,
          words: words.slice(0, wi),
          removed: removed.filter((r) => r < wi),
        };
        segs[rightIdx] = {
          ...B,
          words: words.slice(wi),
          removed: removed.filter((r) => r >= wi).map((r) => r - wi),
        };
        return { ...s, segments: segs };
      });
    },
    [],
  );

  // Crop regions: a list of normalized boxes, each optionally scoped to a time
  // window (multi-range crops). Edited live on the same timeline as Trim —
  // no separate popup/draft state, changes land straight on spec.crops.
  const patchCrop = useCallback((idx: number, patch: Partial<CropRegion>) => {
    setSpec((s) => {
      if (!s) return s;
      const list = cropList(s).map((c, i) =>
        i === idx ? { ...c, ...patch } : c,
      );
      return {
        ...s,
        crops: list,
        crop: { enabled: false, x: 0, y: 0, w: 1, h: 1 },
      };
    });
  }, []);
  const addCrop = useCallback(() => {
    setSpec((s) => {
      if (!s) return s;
      const list = cropList(s);
      const start = Math.round(cur * 1000);
      const end = Math.max(Math.round((dur || cur + 10) * 1000), start + 500);
      setCropSel(list.length);
      return {
        ...s,
        crops: [...list, { ...DEFAULT_CROP, start_ms: start, end_ms: end }],
        crop: { enabled: false, x: 0, y: 0, w: 1, h: 1 },
      };
    });
  }, [cur, dur]);
  const removeCrop = useCallback((idx: number) => {
    setSpec((s) => {
      if (!s) return s;
      const list = cropList(s).filter((_, i) => i !== idx);
      setCropSel((sel) =>
        Math.max(0, Math.min(sel > idx ? sel - 1 : sel, list.length - 1)),
      );
      return {
        ...s,
        crops: list,
        crop: { enabled: false, x: 0, y: 0, w: 1, h: 1 },
      };
    });
  }, []);
  const removeAllCrops = useCallback(() => {
    setCropSel(0);
    setSpec((s) =>
      s
        ? { ...s, crops: [], crop: { enabled: false, x: 0, y: 0, w: 1, h: 1 } }
        : s,
    );
  }, []);

  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    const update = () =>
      setFrameSize({ w: el.clientWidth, h: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [source, showRender]);

  const addElement = useCallback((type: EditElement["type"]) => {
    const el: EditElement =
      type === "text"
        ? {
            id: `el_${Date.now()}`,
            type,
            x: 0.1,
            y: 0.08,
            w: 0.5,
            h: 0.12,
            text: "Your text",
            color: "#111827",
            size: 0.07,
          }
        : {
            id: `el_${Date.now()}`,
            type,
            x: 0.35,
            y: 0.35,
            w: 0.3,
            h: 0.2,
            color: "#6d5dfb",
          };
    setSpec((s) => (s ? { ...s, elements: [...(s.elements ?? []), el] } : s));
    setSelEl(el.id);
  }, []);
  const updateElement = useCallback(
    (elId: string, patch: Partial<EditElement>) =>
      setSpec((s) =>
        s
          ? {
              ...s,
              elements: (s.elements ?? []).map((e) =>
                e.id === elId ? { ...e, ...patch } : e,
              ),
            }
          : s,
      ),
    [],
  );
  const deleteElement = useCallback((elId: string) => {
    setSelEl(null);
    setSpec((s) =>
      s
        ? { ...s, elements: (s.elements ?? []).filter((e) => e.id !== elId) }
        : s,
    );
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
      if (atMs <= seg.source_start_ms + 150 || atMs >= seg.source_end_ms - 150)
        return s;
      const frac =
        (atMs - seg.source_start_ms) /
        (seg.source_end_ms - seg.source_start_ms);
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
  async function rewriteAll(
    instruction?: string,
    mode: "all" | "enhance" = "all",
  ) {
    if (!spec || rewriting !== null) return;
    setRewriting(mode);
    setError(null);
    try {
      const targets = spec.segments
        .map((s, i) => ({ i, t: eff(s) }))
        .filter((x) => x.t.trim());
      if (!targets.length) return;
      const out = await rewriteLines(
        id,
        targets.map((x) => x.t),
        instruction ?? TONE_INSTR[tone],
      );
      setSpec((s) => {
        if (!s) return s;
        const segs = [...s.segments];
        targets.forEach((x, k) => {
          segs[x.i] = {
            ...segs[x.i],
            words: tokenize(out[k] || x.t),
            removed: [],
          };
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
        // on-screen duration → the model budgets ~2-2.5 words/sec so the
        // narration fits the scene and the output length stays correct
        seconds: Math.max(
          1,
          Math.round((s.source_end_ms - s.source_start_ms) / 1000),
        ),
      }));
      const lines = await generateScript(
        id,
        scenes,
        spec.title,
        TONE_INSTR[tone],
      );
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
          zs[i]
            ? {
                ...seg,
                zoom: { ...seg.zoom, enabled: zs[i].zoom, scale: zs[i].scale },
              }
            : seg,
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
      const specAtRender = JSON.stringify(spec);
      const job = await renderVideo(id);
      setRender(job);
      pollRef.current = setInterval(async () => {
        const r = await getRender(job.id);
        setRender(r);
        if (r.status === "done" || r.status === "error") {
          if (pollRef.current) clearInterval(pollRef.current);
          setRendering(false);
          if (r.status === "done") {
            // The renderer persists its auto-added zooms into the spec — pull them
            // in so the Zoom tab shows them for tweaking. Skip the live spec if the
            // user kept editing while the render ran (their edits win).
            try {
              const v = await getVideo(id);
              if (v?.edit_spec) {
                setSavedSpec(v.edit_spec);
                if (JSON.stringify(baseline.current) === specAtRender) {
                  skipHist.current = true;
                  setSpec(v.edit_spec);
                }
              }
            } catch {
              /* non-fatal — reopening the editor shows them */
            }
          }
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

  // Output timeline: the player clock/scrubber run on the FINAL video's clock
  // (pace and skips applied) — mirrors the render pipeline's per-scene timing
  // rules, which keep full source length regardless of voice presence.
  const outMap = useMemo(() => {
    if (!spec) return null;
    const WPS = 2.6;
    const pace = Math.min(1.5, Math.max(1, spec.pace ?? 1.0));
    const useOrig = !!spec.voice.use_original;
    const kept = spec.segments
      .filter((s) => !s.skipped)
      .slice()
      .sort((a, b) => a.source_start_ms - b.source_start_ms);
    let acc = 0;
    const items = kept.map((s) => {
      const src = Math.max(1, s.source_end_ms - s.source_start_ms);
      const words = s.words.filter((_, i) => !s.removed.includes(i));
      const o = !words.length
        ? Math.max(300, src / pace)
        : useOrig
          ? Math.max(300, src / pace)
          : Math.max(
              300,
              (words.length / (WPS * (spec.voice.speed || 1) * pace)) * 1000,
            );
      const it = {
        s0: s.source_start_ms,
        s1: s.source_end_ms,
        o0: acc,
        o1: acc + o,
      };
      acc += o;
      return it;
    });
    return { items, total: acc };
  }, [spec]);
  const outTotalSec = outMap && outMap.items.length ? outMap.total / 1000 : dur;
  const toOutSec = (srcSec: number) => {
    if (!outMap || !outMap.items.length) return srcSec;
    const t = srcSec * 1000;
    let last = 0;
    for (const it of outMap.items) {
      if (t < it.s0) return last / 1000; // inside a dropped gap → hold at previous scene's end
      if (t < it.s1)
        return (
          (it.o0 + ((t - it.s0) / (it.s1 - it.s0)) * (it.o1 - it.o0)) / 1000
        );
      last = it.o1;
    }
    return outMap.total / 1000;
  };
  const toSrcSec = (outSec: number) => {
    if (!outMap || !outMap.items.length) return outSec;
    const o = outSec * 1000;
    for (const it of outMap.items) {
      if (o <= it.o1) {
        const f = Math.max(
          0,
          Math.min(1, (o - it.o0) / Math.max(1, it.o1 - it.o0)),
        );
        return (it.s0 + f * (it.s1 - it.s0)) / 1000;
      }
    }
    return outMap.items[outMap.items.length - 1].s1 / 1000;
  };

  useEffect(() => {
    if (playing && tab === "Script")
      activeRef.current?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIdx, playing, tab]);

  if (!spec) {
    return (
      <main className="mx-auto max-w-4xl px-6 py-12">
        <Link href={`/projects/${id}`} className="btn btn-ghost btn-sm -ml-2">
          ← Project
        </Link>
        <div className="card mt-6 p-6 text-sm text-[var(--text-2)]">
          {error ??
            "No video yet — process a capture into a Workflow Graph first."}
        </div>
      </main>
    );
  }

  const activeSeg = activeIdx >= 0 ? spec.segments[activeIdx] : null;
  const zoomOn = !!activeSeg?.zoom.enabled && (playing || tab === "Zoom");
  const zoomSpeed = activeSeg?.zoom.speed ?? 3;
  const zoomStyle: React.CSSProperties = {
    transform: zoomOn ? `scale(${activeSeg!.zoom.scale})` : "scale(1)",
    transformOrigin: activeSeg
      ? `${activeSeg.zoom.cx * 100}% ${activeSeg.zoom.cy * 100}%`
      : "center",
    transition: `transform ${((6 - zoomSpeed) * 0.3).toFixed(2)}s ease`,
  };
  const captionText = spec.captions.enabled && activeSeg ? eff(activeSeg) : "";

  // Backdrop behind the recording (inset), mirrored by the renderer.
  const bgOn = !!spec.background?.enabled;
  const bgCss =
    BG_PRESETS.find((p) => p.id === spec.background?.style)?.css ??
    BG_PRESETS[0].css;
  // Crop reframe: actually show the cropped region filling the frame (the render
  // does the same), not just a dimmed outline. Multi-range crops — the playhead
  // picks which region is in effect (legacy single crop folded in).
  const crops = cropList(spec);
  const cr = activeCrop(crops, cur * 1000);
  // clamp so x+w / y+h can never exceed the frame — an out-of-bounds region makes
  // the origin math point at the wrong area entirely
  const cw = Math.min(1, Math.max(0.05, cr?.w ?? 1));
  const ch = Math.min(1, Math.max(0.05, cr?.h ?? 1));
  const cx = Math.min(Math.max(0, cr?.x ?? 0), 1 - cw);
  const cy = Math.min(Math.max(0, cr?.y ?? 0), 1 - ch);
  const cropOn = !!cr && (cw < 0.999 || ch < 0.999 || cx > 0.001 || cy > 0.001);
  // Uniform cover-scale about the region center, then shift that center to the
  // middle of the frame — same "crop, then cover" the render does, so the
  // preview shows exactly the selected content with no stretch and no padding.
  const cropScale = Math.max(1 / cw, 1 / ch);
  // While actively editing a crop region, show the full raw frame instead of
  // the reframed preview so the box can be dragged against the whole source.
  const cropStyle: React.CSSProperties =
    cropOn && activeTool !== "crop"
      ? {
          transform: `translate(${((0.5 - (cx + cw / 2)) * 100).toFixed(2)}%, ${(
            (0.5 - (cy + ch / 2)) *
            100
          ).toFixed(2)}%) scale(${cropScale.toFixed(4)})`,
          transformOrigin: `${((cx + cw / 2) * 100).toFixed(2)}% ${((cy + ch / 2) * 100).toFixed(2)}%`,
        }
      : {};

  const totalMs =
    (dur ? dur * 1000 : 0) ||
    spec.segments.reduce((m, s) => Math.max(m, s.source_end_ms || 0), 0) ||
    1;
  const query = q.trim().toLowerCase();

  const CHIPS: {
    key: Tab | "trim" | "crop" | "soon" | "enhance";
    label: string;
    icon: string;
    soon?: boolean;
  }[] = [
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
      {/* header */}
      <header className="flex items-center justify-between gap-4 border-b border-[var(--border)] bg-[var(--card)] px-6 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <Link
            href={`/projects/${id}`}
            className="btn btn-ghost btn-sm -ml-1"
            title="Back"
          >
            ←
          </Link>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <input
                value={spec.title}
                onChange={(e) => setSpec({ ...spec, title: e.target.value })}
                title="Video title — also used as the Intro card text"
                className="min-w-0 flex-1 truncate rounded px-1 -mx-1 text-[17px] font-semibold tracking-tight text-[var(--text)] hover:bg-[var(--hover)] focus:bg-[var(--hover)] focus:outline-none"
              />
              <Link
                href={`/projects/${id}/document`}
                className="rounded-lg px-2 py-0.5 text-xs font-medium text-[var(--text-2)] hover:bg-[var(--hover)]"
              >
                Document
              </Link>
            </div>
            <div className="text-[11px] text-[var(--text-3)]">
              {saving
                ? "Saving…"
                : dirty
                  ? "Unsaved changes"
                  : "Saved just now"}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {!dirty && (
            <span className="hidden text-xs text-[var(--text-3)] sm:inline">
              Saved
            </span>
          )}
          <select
            value={String(spec.pace ?? 1.0)}
            onChange={(e) => setSpec({ ...spec, pace: Number(e.target.value) })}
            title="Video pace — applies the same tempo to every scene, narrated or silent"
            className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 py-1.5 text-xs text-[var(--text-2)]"
          >
            {[1, 1.1, 1.25, 1.5].map((p) => (
              <option key={p} value={p}>
                {p}× pace
              </option>
            ))}
          </select>
          <ShareButton projectId={id} kind="video" />
          <button
            onClick={doRender}
            disabled={rendering}
            className="btn btn-primary btn-sm"
          >
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
                  tab === t
                    ? "bg-[#6d5dfb]/10 text-[#6d5dfb]"
                    : "text-[var(--text-2)] hover:bg-[var(--hover)]"
                }`}
              >
                {t}
              </button>
            ))}
            {TOOL_TABS.includes(tab) && (
              <span className="ml-auto flex items-center gap-2 text-xs text-[var(--text-2)]">
                {tab}
                <button
                  onClick={() => setTab("Script")}
                  className="btn btn-ghost btn-sm"
                >
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
                    <span className="text-xs font-medium text-amber-500">
                      Unsaved edits
                    </span>
                    <div className="ml-auto flex items-center gap-2">
                      <button
                        onClick={discard}
                        disabled={saving}
                        className="btn btn-ghost btn-sm"
                      >
                        Discard
                      </button>
                      <button
                        onClick={save}
                        disabled={saving}
                        className="btn btn-secondary btn-sm"
                      >
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
                          <span className="badge bg-amber-100 text-amber-700">
                            edited
                          </span>
                        )}
                        <div className="ml-auto flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                          <IconBtn
                            title="Edit"
                            onClick={() => setEditIdx(editIdx === i ? null : i)}
                          >
                            ✏
                          </IconBtn>
                          <IconBtn
                            title="Voice"
                            onClick={() => setTab("AI Voice")}
                          >
                            🎤
                          </IconBtn>
                          <IconBtn
                            title="AI Rewrite this line"
                            onClick={() => rewriteOne(i)}
                            disabled={rewriting !== null}
                          >
                            {rewriting === i ? "…" : "⚡"}
                          </IconBtn>
                          <IconBtn
                            title="Delete"
                            onClick={() => deleteSegment(i)}
                            danger
                          >
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
                                  struck
                                    ? "text-[#c4c9d6] line-through"
                                    : "hover:bg-[#6d5dfb]/10"
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
                  onChange={(patch) =>
                    setSpec({ ...spec, voice: { ...spec.voice, ...patch } })
                  }
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

            {tab === "Background" && (
              <BackgroundPanel spec={spec} patchSpec={patchSpec} />
            )}

            {tab === "Intro" && (
              <IntroOutroPanel spec={spec} patchSpec={patchSpec} />
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
                {render.status === "done" && render.output_key && (
                  <button
                    onClick={() =>
                      downloadMedia(render.output_key!, `${render.output_key!.split("/").pop()}`)
                    }
                    className="btn btn-ghost btn-sm ml-auto"
                  >
                    ↓ Download
                  </button>
                )}
                <button
                  onClick={() => setShowRender(false)}
                  className={`btn btn-ghost btn-sm ${
                    render.status === "done" && render.output_key ? "" : "ml-auto"
                  }`}
                >
                  ← back to preview
                </button>
              </div>
              {render.status === "done" && render.output_key ? (
                <video
                  src={mediaUrl(render.output_key)}
                  controls
                  className="w-full rounded-2xl bg-black shadow-sm"
                />
              ) : (
                <div className="flex items-center justify-center gap-2 rounded-2xl border border-[var(--border)] bg-[var(--card)] py-24 text-sm text-[var(--text-2)]">
                  {render.status === "error" ? (
                    <span className="text-red-600">
                      {JSON.stringify(render.error_json)}
                    </span>
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
                    className="relative flex h-full max-h-full items-center justify-center overflow-hidden rounded-2xl shadow-lg"
                    style={{
                      background: bgOn ? bgCss : "#000",
                      padding: bgOn ? "1.3% 2.6%" : undefined,
                    }}
                  >
                    <div
                      className={`relative flex max-h-full min-h-0 items-center justify-center overflow-hidden ${bgOn ? "rounded-xl shadow-lg" : ""}`}
                    >
                      <div
                        className="flex max-h-full min-h-0 items-center justify-center"
                        style={cropStyle}
                      >
                        <video
                          ref={videoRef}
                          src={mediaUrl(source)}
                          className="max-h-full w-auto"
                          style={zoomStyle}
                          onLoadedMetadata={(e) => {
                            resolveDuration(e.currentTarget, setDur);
                            e.currentTarget.muted = wantAiVoice;
                            e.currentTarget.playbackRate = rate;
                          }}
                          onTimeUpdate={(e) => {
                            const v = e.currentTarget;
                            setCur(v.currentTime);
                            if (v.paused) return; // free scrubbing while paused
                            // Preview the PROCESSED video: while playing, stay on kept
                            // scenes only — skipped scenes AND the dead source gaps
                            // between scenes (which the render drops) are jumped over.
                            const nowMs = v.currentTime * 1000;
                            const kept = spec.segments
                              .filter((sg) => !sg.skipped)
                              .sort(
                                (a, b) => a.source_start_ms - b.source_start_ms,
                              );
                            if (kept.length) {
                              const inside = kept.some(
                                (sg) =>
                                  nowMs + 40 >= sg.source_start_ms &&
                                  nowMs < sg.source_end_ms,
                              );
                              if (!inside) {
                                const next = kept.find(
                                  (sg) => sg.source_start_ms >= nowMs - 1,
                                );
                                if (next)
                                  v.currentTime = next.source_start_ms / 1000;
                                else {
                                  v.pause();
                                  v.currentTime =
                                    kept[0].source_start_ms / 1000;
                                }
                                return;
                              }
                            }
                            const tr = spec.trim;
                            if (
                              tr?.enabled &&
                              tr.end_ms > tr.start_ms &&
                              v.currentTime * 1000 >= tr.end_ms
                            ) {
                              v.pause();
                              v.currentTime = tr.start_ms / 1000;
                            }
                          }}
                          onPlay={(e) => {
                            setPlaying(true);
                            e.currentTarget.muted = wantAiVoice;
                            if (aiVoiceActive && audioRef.current) {
                              audioRef.current.currentTime =
                                e.currentTarget.currentTime;
                              void audioRef.current.play().catch(() => {});
                            }
                          }}
                          onPause={() => {
                            setPlaying(false);
                            audioRef.current?.pause();
                          }}
                          onSeeked={(e) => {
                            if (aiVoiceActive && audioRef.current)
                              audioRef.current.currentTime =
                                e.currentTarget.currentTime;
                          }}
                        />
                      </div>
                    </div>
                    <audio
                      ref={audioRef}
                      src={voiceUrl ?? undefined}
                      preload="auto"
                    />
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
                      cropEditing={activeTool === "crop"}
                      crops={crops}
                      cropSel={cropSel}
                      onPatchCrop={patchCrop}
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
                    if (videoRef.current)
                      videoRef.current.muted = !videoRef.current.muted;
                  }}
                  className="btn btn-ghost btn-sm"
                  title="Mute / unmute"
                >
                  🔊
                </button>
                <span
                  className="font-mono text-xs text-[var(--text-2)]"
                  title="Final video time (pace & cuts applied)"
                >
                  {clock(toOutSec(cur))} / {clock(outTotalSec)}
                </span>
                <input
                  type="range"
                  min={0}
                  max={outTotalSec || 1}
                  step={0.05}
                  value={Math.min(outTotalSec, toOutSec(cur))}
                  onChange={(e) => seekTo(toSrcSec(Number(e.target.value)))}
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
                <button
                  onClick={fullscreen}
                  className="btn btn-ghost btn-sm"
                  title="Fullscreen"
                >
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
                    ⚠ Couldn’t build the AI voice preview — is the worker
                    running?
                  </span>
                ) : aiVoiceActive ? (
                  <>
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />{" "}
                    Preview plays the AI voice — Generate for exact timing.
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
              title={
                c.soon
                  ? "Coming soon"
                  : c.key === "enhance"
                    ? "Tighten the whole script with AI"
                    : c.label
              }
              onClick={() => {
                if (c.soon) return;
                if (c.key === "enhance") void enhance();
                else if (c.key === "Captions")
                  setSpec({
                    ...spec,
                    captions: { enabled: !spec.captions.enabled },
                  });
                else if (c.key === "trim") {
                  // Trim swaps the timeline below to a focused single-track view
                  // (inline, no popup) — click again to go back to the full timeline.
                  videoRef.current?.pause();
                  setActiveTool((t) => (t === "trim" ? null : "trim"));
                  timelineRef.current?.scrollIntoView({
                    behavior: "smooth",
                    block: "end",
                  });
                } else if (c.key === "crop") {
                  // Crop swaps the timeline below to a region-editing track (same
                  // pattern as Trim) and shows a draggable box on the preview above.
                  videoRef.current?.pause();
                  if (activeTool !== "crop") {
                    const list = cropList(spec);
                    if (!list.length)
                      setSpec({ ...spec, crops: [{ ...DEFAULT_CROP }] });
                    setCropSel((sel) =>
                      Math.min(sel, Math.max(0, list.length - 1)),
                    );
                    timelineRef.current?.scrollIntoView({
                      behavior: "smooth",
                      block: "end",
                    });
                  }
                  setActiveTool((t) => (t === "crop" ? null : "crop"));
                } else setTab(c.key as Tab);
              }}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-all ${
                active || capOn
                  ? "border-[#6d5dfb] bg-[#6d5dfb]/10 text-[#6d5dfb]"
                  : "border-[var(--border)] bg-[var(--bg)] text-[var(--text-2)] hover:bg-[var(--hover)]"
              } ${c.soon ? "opacity-40" : ""}`}
            >
              {busy ? (
                <Spinner />
              ) : (
                <span className="text-[13px]">{c.icon}</span>
              )}
              {c.label}
            </button>
          );
        })}
      </div>

      {/* TIMELINE — Trim/Crop swap in a focused single-track view; otherwise the
          full Video/Audio/Voice/Captions/Zoom timeline. All edit the same spec live. */}
      {activeTool === "trim" ? (
        <TrimTrack
          sectionRef={timelineRef}
          spec={spec}
          source={source}
          cur={cur}
          dur={dur}
          activeIdx={activeIdx}
          tlZoom={tlZoom}
          setTlZoom={setTlZoom}
          seekTo={seekTo}
          onMoveBoundary={moveBoundary}
          onFinalizeBoundary={finalizeBoundary}
          onDelete={() => activeIdx >= 0 && deleteSegment(activeIdx)}
          onDuplicate={() => activeIdx >= 0 && duplicateSegment(activeIdx)}
          onSkip={() => activeIdx >= 0 && toggleSkip(activeIdx)}
          onSplit={() => activeIdx >= 0 && splitSegment(activeIdx, cur * 1000)}
          onUndo={undo}
          onRedo={redo}
          canUndo={histState.canUndo}
          canRedo={histState.canRedo}
          onDone={() => setActiveTool(null)}
        />
      ) : activeTool === "crop" ? (
        <CropTrack
          sectionRef={timelineRef}
          source={source}
          cur={cur}
          dur={dur}
          crops={crops}
          cropSel={cropSel}
          setCropSel={setCropSel}
          seekTo={seekTo}
          onPatchCrop={patchCrop}
          onAddCrop={addCrop}
          onRemoveCrop={removeCrop}
          onRemoveAll={removeAllCrops}
          onDone={() => setActiveTool(null)}
        />
      ) : (
        <TimelineTracks
          sectionRef={timelineRef}
          spec={spec}
          source={source}
          totalMs={totalMs}
          cur={cur}
          dur={dur}
          activeIdx={activeIdx}
          useOriginal={!!useOriginal}
          tlZoom={tlZoom}
          seekTo={seekTo}
          onMove={moveSegment}
          onResize={resizeSegment}
          onResizeStart={resizeSegmentStart}
        />
      )}
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
        danger
          ? "text-[var(--text-3)] hover:bg-red-50 hover:text-red-500"
          : "text-[var(--text-2)] hover:bg-[var(--hover)]"
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
  if (!spec.segments.length)
    return <p className="text-sm text-[var(--text-3)]">No scenes to zoom.</p>;
  // a manual tweak takes ownership of an auto-added zoom (drops the "auto" badge)
  const setZoomAt = (i: number, patch: Partial<EditSegment["zoom"]>) =>
    mutateSeg(i, { zoom: { ...spec.segments[i].zoom, ...patch, auto: false } });
  const pickPosAt = (i: number) => (e: React.PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setZoomAt(i, {
      enabled: true,
      cx: Number(
        Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)).toFixed(3),
      ),
      cy: Number(
        Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)).toFixed(3),
      ),
    });
  };
  return (
    <div className="space-y-5">
      <label className="flex cursor-pointer items-start justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] p-3">
        <span>
          <span className="text-sm font-medium">Auto-zoom on mouse clicks</span>
          <span className="mt-0.5 block text-xs text-[var(--text-2)]">
            Track cursor/click activity and zoom toward it on scenes without a
            manual zoom.
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
        <div className="mb-1 flex items-center justify-between">
          <span className="label">Scenes</span>
          <span className="text-xs text-[var(--text-3)]">
            {
              spec.segments.filter(
                (s) => s.zoom.enabled || s.zoom.auto !== false,
              ).length
            }{" "}
            of {spec.segments.length} zoomed
          </span>
        </div>
        {/* one box per scene — click to expand its own position / level / speed editor.
            Default state is ACTIVE (auto): the generator zooms toward the mouse click
            unless the user turns the scene off. */}
        <div className="space-y-2 pr-0.5">
          {spec.segments.map((s, i) => {
            const open = zi === i;
            const displayOn = s.zoom.enabled || s.zoom.auto !== false; // auto is the default
            return (
              <div
                key={s.step_id}
                onClick={() => {
                  setZoomIdx(i);
                  seekTo(s.source_start_ms / 1000);
                }}
                className={`cursor-pointer rounded-xl border p-2.5 transition-colors ${
                  open
                    ? "border-[#6d5dfb] bg-[#6d5dfb]/5"
                    : displayOn
                      ? "border-[var(--border)] bg-[var(--card)] hover:bg-[var(--hover)]"
                      : "border-dashed border-[var(--border)] bg-[var(--bg)] hover:bg-[var(--hover)]"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="w-5 flex-none text-right font-mono text-[11px] text-[var(--text-3)]">
                    {i + 1}
                  </span>
                  <span className="flex-none font-mono text-[11px] text-[#6d5dfb]">
                    {mmss(s.source_start_ms / 1000)}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium">
                    {s.target ?? "Scene"}
                  </span>
                  {displayOn && !open && (
                    <span
                      className={`badge flex-none ${
                        s.zoom.enabled && !s.zoom.auto
                          ? "bg-[#6d5dfb]/10 text-[#6d5dfb]"
                          : "bg-amber-100 text-amber-700"
                      }`}
                    >
                      {s.zoom.enabled
                        ? `${s.zoom.auto ? "auto" : "zoom"} ${Math.round(s.zoom.scale * 100)}%`
                        : "auto"}
                    </span>
                  )}
                  <label
                    onClick={(e) => e.stopPropagation()}
                    className="flex flex-none cursor-pointer items-center gap-1.5 text-[11px] font-medium text-[var(--text-2)]"
                    title={
                      displayOn
                        ? "Turn zoom off for this scene"
                        : "Turn zoom back on (auto position)"
                    }
                  >
                    {displayOn ? "Active" : "Off"}
                    <input
                      type="checkbox"
                      checked={displayOn}
                      onChange={(e) =>
                        // off = explicit opt-out (generator respects it);
                        // on = back to auto (position picked from the click at generate)
                        mutateSeg(i, {
                          zoom: {
                            ...s.zoom,
                            enabled: false,
                            auto: e.target.checked,
                          },
                        })
                      }
                      className="h-4 w-8 accent-[#6d5dfb]"
                    />
                  </label>
                </div>

                {/* expanded editor for the selected scene */}
                {open && s.zoom.enabled && (
                  <div
                    onClick={(e) => e.stopPropagation()}
                    className="mt-2.5 cursor-default space-y-3 border-t border-[var(--border)] pt-2.5"
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`badge ${s.zoom.auto ? "bg-amber-100 text-amber-700" : "bg-[#6d5dfb]/10 text-[#6d5dfb]"}`}
                      >
                        {s.zoom.auto ? "auto zoom" : "zoom"}
                      </span>
                      <span className="text-[11px] text-[var(--text-3)]">
                        center {Math.round(s.zoom.cx * 100)},
                        {Math.round(s.zoom.cy * 100)}
                      </span>
                    </div>
                    <div>
                      <div className="mb-1 text-[11px] font-medium text-[var(--text-2)]">
                        Zoom position — click to aim
                      </div>
                      <div
                        onPointerDown={(e) => {
                          e.currentTarget.setPointerCapture(e.pointerId);
                          pickPosAt(i)(e);
                        }}
                        onPointerMove={(e) =>
                          e.buttons === 1 && pickPosAt(i)(e)
                        }
                        className="relative grid aspect-video w-full cursor-crosshair grid-cols-6 grid-rows-4 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg)]"
                      >
                        {Array.from({ length: 24 }).map((_, k) => (
                          <div
                            key={k}
                            className="border border-[var(--border)]/70"
                          />
                        ))}
                        <span
                          style={{
                            left: `${s.zoom.cx * 100}%`,
                            top: `${s.zoom.cy * 100}%`,
                          }}
                          className="pointer-events-none absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#6d5dfb] shadow ring-2 ring-white"
                        />
                      </div>
                    </div>
                    {(
                      [
                        [
                          "Zoom level",
                          Math.round(s.zoom.scale * 100),
                          100,
                          250,
                          5,
                          (v: number) =>
                            setZoomAt(i, { enabled: true, scale: v / 100 }),
                        ],
                        [
                          "Zoom speed",
                          s.zoom.speed ?? 3,
                          1,
                          5,
                          1,
                          (v: number) => setZoomAt(i, { speed: v }),
                        ],
                      ] as const
                    ).map(([label, val, min, max, step, on]) => (
                      <div key={label}>
                        <div className="mb-1 flex items-center justify-between">
                          <span className="text-[11px] font-medium text-[var(--text-2)]">
                            {label}
                          </span>
                          <span className="rounded border border-[var(--border)] px-1.5 text-xs">
                            {val}
                          </span>
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
                    <button
                      onClick={() => setZoomAt(i, { enabled: false })}
                      className="btn btn-secondary btn-sm w-full"
                    >
                      🗑 Remove zoom from this scene
                    </button>
                  </div>
                )}

                {open && !s.zoom.enabled && displayOn && (
                  <div
                    onClick={(e) => e.stopPropagation()}
                    className="mt-2.5 cursor-default space-y-2.5 border-t border-[var(--border)] pt-2.5"
                  >
                    <p className="text-[11px] text-[var(--text-3)]">
                      <span className="badge mr-1.5 bg-amber-100 text-amber-700">
                        auto
                      </span>
                      Position is picked from your mouse click when the video
                      generates. Click the grid to set it manually instead.
                    </p>
                    <div
                      onPointerDown={(e) => {
                        e.currentTarget.setPointerCapture(e.pointerId);
                        pickPosAt(i)(e);
                      }}
                      onPointerMove={(e) => e.buttons === 1 && pickPosAt(i)(e)}
                      className="relative grid aspect-video w-full cursor-crosshair grid-cols-6 grid-rows-4 overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg)]"
                    >
                      {Array.from({ length: 24 }).map((_, k) => (
                        <div
                          key={k}
                          className="border border-[var(--border)]/70"
                        />
                      ))}
                    </div>
                  </div>
                )}

                {open && !displayOn && (
                  <p className="mt-2 pl-7 text-[11px] text-[var(--text-3)]">
                    Zoom is off for this scene — the generator will leave it
                    wide. Switch to Active to zoom again.
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function BackgroundPanel({
  spec,
  patchSpec,
}: {
  spec: EditSpec;
  patchSpec: (p: Partial<EditSpec>) => void;
}) {
  const cur = spec.background?.enabled ? spec.background.style : "none";
  const music = spec.music ?? {
    enabled: false,
    storage_key: null,
    gain_db: -18,
  };
  const pick = (id: string) =>
    patchSpec({
      background:
        id === "none"
          ? { enabled: false, style: spec.background?.style ?? "indigo" }
          : { enabled: true, style: id },
    });
  return (
    <div className="space-y-4">
      <p className="text-xs text-[var(--text-3)]">
        Put the recording on a colored backdrop — it renders inset with padding
        instead of full-bleed on black. Applies to the preview and the generated
        video.
      </p>
      <div className="grid grid-cols-2 gap-2">
        {[
          { id: "none", label: "None — full bleed", css: "#0b0f1a" },
          ...BG_PRESETS,
        ].map((p) => (
          <button
            key={p.id}
            onClick={() => pick(p.id)}
            className={`rounded-xl border p-2 text-left transition-all ${
              cur === p.id
                ? "border-[#6d5dfb] ring-2 ring-[#6d5dfb]/40"
                : "border-[var(--border)] hover:bg-[var(--hover)]"
            }`}
          >
            <span
              className="mb-1.5 block h-12 w-full rounded-lg"
              style={{ background: p.css }}
            >
              {p.id !== "none" && (
                <span className="flex h-full items-center justify-center">
                  <span className="h-7 w-3/5 rounded-sm bg-white/85 shadow" />
                </span>
              )}
            </span>
            <span className="text-xs font-medium">{p.label}</span>
          </button>
        ))}
      </div>

      {/* background music — soft ambient pad mixed under the narration */}
      <div className="border-t border-[var(--border)] pt-4">
        <label className="flex cursor-pointer items-center justify-between">
          <span>
            <span className="text-sm font-medium">Background music</span>
            <span className="mt-0.5 block text-xs text-[var(--text-3)]">
              A smooth, slow ambient pad under the narration. Mixed into the
              generated video.
            </span>
          </span>
          <input
            type="checkbox"
            checked={music.enabled}
            onChange={(e) =>
              patchSpec({ music: { ...music, enabled: e.target.checked } })
            }
            className="h-4 w-8 accent-[#6d5dfb]"
          />
        </label>
        {music.enabled && (
          <div className="mt-3 flex items-center gap-3 text-xs">
            <span className="text-[var(--text-3)]">Quiet</span>
            <input
              type="range"
              min={-30}
              max={-8}
              step={1}
              value={music.gain_db ?? -18}
              onChange={(e) =>
                patchSpec({
                  music: { ...music, gain_db: Number(e.target.value) },
                })
              }
              className="flex-1 accent-[#6d5dfb]"
            />
            <span className="text-[var(--text-3)]">Loud</span>
            <span className="w-12 text-right font-mono text-[var(--text-2)]">
              {music.gain_db ?? -18} dB
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function IntroOutroPanel({
  spec,
  patchSpec,
}: {
  spec: EditSpec;
  patchSpec: (p: Partial<EditSpec>) => void;
}) {
  const intro = spec.intro ?? {
    enabled: false,
    title: spec.title,
    duration_ms: 2000,
  };
  const outro = spec.outro ?? {
    enabled: false,
    title: "Thanks for watching",
    duration_ms: 1500,
  };
  return (
    <div className="space-y-5">
      <p className="text-xs text-[var(--text-3)]">
        Title cards shown before and after the recording. Turn either off to
        skip it entirely.
      </p>

      {(
        [
          [
            "Intro",
            intro,
            (p: Partial<EditSpec["intro"]>) =>
              patchSpec({ intro: { ...intro, ...p } }),
            500,
            5000,
          ],
          [
            "Outro",
            outro,
            (p: Partial<EditSpec["outro"]>) =>
              patchSpec({ outro: { ...outro, ...p } }),
            500,
            5000,
          ],
        ] as const
      ).map(([label, card, set, minMs, maxMs]) => (
        <div
          key={label}
          className="rounded-xl border border-[var(--border)] p-3"
        >
          <label className="flex cursor-pointer items-center justify-between">
            <span className="text-sm font-medium">{label}</span>
            <input
              type="checkbox"
              checked={card.enabled}
              onChange={(e) => set({ enabled: e.target.checked })}
              className="h-4 w-8 accent-[#6d5dfb]"
            />
          </label>
          {card.enabled && (
            <div className="mt-3 space-y-3">
              <input
                value={card.title}
                onChange={(e) => set({ title: e.target.value })}
                placeholder={`${label} text`}
                className="input"
              />
              <div className="flex items-center gap-3 text-xs">
                <span className="text-[var(--text-3)]">Short</span>
                <input
                  type="range"
                  min={minMs}
                  max={maxMs}
                  step={100}
                  value={card.duration_ms}
                  onChange={(e) => set({ duration_ms: Number(e.target.value) })}
                  className="flex-1 accent-[#6d5dfb]"
                />
                <span className="text-[var(--text-3)]">Long</span>
                <span className="w-14 text-right font-mono text-[var(--text-2)]">
                  {(card.duration_ms / 1000).toFixed(1)}s
                </span>
              </div>
            </div>
          )}
        </div>
      ))}
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
      <p className="text-xs text-[var(--text-3)]">
        Add text or a highlight box, then drag/resize it on the preview.
      </p>
      <div className="flex gap-2">
        <button
          onClick={() => addElement("text")}
          className="btn btn-secondary btn-sm"
        >
          + Text
        </button>
        <button
          onClick={() => addElement("box")}
          className="btn btn-secondary btn-sm"
        >
          + Highlight box
        </button>
      </div>
      {els.length === 0 && (
        <p className="text-xs text-[var(--text-3)]">No elements yet.</p>
      )}
      <div className="space-y-1.5">
        {els.map((el) => (
          <button
            key={el.id}
            onClick={() => setSelEl(el.id)}
            className={`flex w-full items-center gap-2 rounded-xl border px-3 py-2 text-left text-sm ${
              selEl === el.id
                ? "border-[#6d5dfb]/40 bg-[#6d5dfb]/5"
                : "border-[var(--border)] hover:bg-[var(--hover)]"
            }`}
          >
            <span className="text-xs uppercase text-[var(--text-3)]">
              {el.type}
            </span>
            <span className="truncate">
              {el.type === "text" ? el.text || "Text" : "Highlight"}
            </span>
          </button>
        ))}
      </div>
      {sel && (
        <div className="space-y-3 rounded-xl border border-[var(--border)] p-3">
          {sel.type === "text" && (
            <div>
              <div className="label mb-1">Text</div>
              <input
                value={sel.text ?? ""}
                onChange={(e) =>
                  updateElement(sel.id, { text: e.target.value })
                }
                className="input"
              />
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
            <button
              onClick={() => deleteElement(sel.id)}
              className="btn btn-ghost btn-sm ml-auto text-red-500"
            >
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
                      ? {
                          start_ms: Math.round(cur * 1000),
                          end_ms: Math.round(Math.min(dur, cur + 5) * 1000),
                        }
                      : { start_ms: 0, end_ms: 0 },
                  )
                }
                className="h-4 w-8 accent-[#6d5dfb]"
              />
            </label>
            {(sel.end_ms ?? 0) > (sel.start_ms ?? 0) && (
              <div className="mt-2 space-y-2">
                {(["From", "To"] as const).map((which) => {
                  const val =
                    which === "From" ? (sel.start_ms ?? 0) : (sel.end_ms ?? 0);
                  return (
                    <div key={which} className="flex items-center gap-2">
                      <span className="w-9 text-xs text-[var(--text-3)]">
                        {which}
                      </span>
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
                              ? {
                                  start_ms: Math.min(
                                    v,
                                    (sel.end_ms ?? 0) - 200,
                                  ),
                                }
                              : {
                                  end_ms: Math.max(
                                    v,
                                    (sel.start_ms ?? 0) + 200,
                                  ),
                                },
                          );
                        }}
                        className="flex-1 accent-[#6d5dfb]"
                      />
                      <span className="w-11 text-right font-mono text-xs text-[var(--text-2)]">
                        {mmss(val / 1000)}
                      </span>
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
  sectionRef,
  spec,
  source,
  totalMs,
  cur,
  dur,
  activeIdx,
  useOriginal,
  tlZoom,
  seekTo,
  onMove,
  onResize,
  onResizeStart,
}: {
  sectionRef?: React.RefObject<HTMLElement>;
  spec: EditSpec;
  source: string | null;
  totalMs: number;
  cur: number;
  dur: number;
  activeIdx: number;
  useOriginal: boolean;
  tlZoom: number;
  seekTo: (s: number) => void;
  onMove: (i: number, startMs: number) => void;
  onResize: (i: number, endMs: number) => void;
  onResizeStart: (i: number, startMs: number) => void;
}) {
  const frames = useFilmstrip(source, 24);
  const peaks = useWaveform(source, 400);
  const blocks = spec.segments.map((s, i) => {
    const left = (s.source_start_ms / totalMs) * 100;
    const width = Math.max(
      1.5,
      ((Math.max(s.source_end_ms, s.source_start_ms + 400) -
        s.source_start_ms) /
        totalMs) *
        100,
    );
    return { s, i, left, width, text: eff(s) };
  });
  const ROWS: { label: string; render: () => React.ReactNode }[] = [
    {
      label: "Video",
      render: () => (
        <>
          {/* real frame thumbnails behind the selectable/draggable scene blocks */}
          <Filmstrip frames={frames} className="rounded-md opacity-90" />
          {blocks.map((b) => (
            <DraggableBlock
              key={b.s.step_id}
              b={b}
              totalMs={totalMs}
              active={activeIdx === b.i}
              skipped={!!b.s.skipped}
              onSeek={() => seekTo(b.s.source_start_ms / 1000)}
              onMove={(startMs) => onMove(b.i, startMs)}
              onResize={(endMs) => onResize(b.i, endMs)}
              onResizeStart={(startMs) => onResizeStart(b.i, startMs)}
            />
          ))}
        </>
      ),
    },
    {
      label: "Audio",
      render: () => (
        <div className="absolute inset-x-1 top-1/2 h-7 -translate-y-1/2 text-[var(--brand-2)]">
          <Waveform peaks={peaks} className="opacity-80" />
        </div>
      ),
    },
    {
      label: "Voice",
      render: () =>
        useOriginal
          ? null
          : blocks.map((b) => (
              <TlBlock
                key={b.s.step_id}
                b={b}
                active={false}
                onClick={() => seekTo(b.s.source_start_ms / 1000)}
                tone="voice"
              />
            )),
    },
    {
      label: "Captions",
      render: () =>
        spec.captions.enabled
          ? blocks.map((b) => (
              <TlBlock
                key={b.s.step_id}
                b={b}
                active={false}
                onClick={() => seekTo(b.s.source_start_ms / 1000)}
                tone="cap"
                label={b.text}
              />
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
    <section
      ref={sectionRef}
      className="border-t border-[var(--border)] bg-[var(--card)] px-6 py-3"
    >
      {/* Undo/Redo/Split/Skip/Duplicate/Delete/Zoom live in Trim mode only — this
          overview timeline is drag-to-move/resize plus click-to-seek. */}
      {/* ruler */}
      <div className="relative ml-20 h-4 overflow-hidden text-[10px] text-[var(--text-3)]">
        {Array.from({ length: 11 }).map((_, i) => (
          <span
            key={i}
            style={{ left: `${(i / 10) * 100}%` }}
            className="absolute -translate-x-1/2"
          >
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
              <div
                data-track
                className="relative h-full"
                style={{ width: `${tlZoom * 100}%`, minWidth: "100%" }}
              >
                {row.render()}
                {/* playhead */}
                {dur > 0 && (
                  <div
                    style={{
                      left: `${Math.min(100, (cur / (totalMs / 1000)) * 100)}%`,
                    }}
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

function TimelineToolbar({
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  onSplit,
  onSkip,
  skipActive,
  onDuplicate,
  onDelete,
  tlZoom,
  setTlZoom,
  trailing,
}: {
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  onSplit: () => void;
  onSkip: () => void;
  skipActive: boolean;
  onDuplicate: () => void;
  onDelete: () => void;
  tlZoom: number;
  setTlZoom: (n: number) => void;
  trailing?: React.ReactNode;
}) {
  return (
    <div className="mb-2 flex items-center gap-1 text-[var(--text-2)]">
      <button
        onClick={onUndo}
        disabled={!canUndo}
        title="Undo (⌘Z)"
        className="btn btn-ghost btn-sm"
      >
        ↶ Undo
      </button>
      <button
        onClick={onRedo}
        disabled={!canRedo}
        title="Redo (⌘⇧Z)"
        className="btn btn-ghost btn-sm"
      >
        ↷ Redo
      </button>
      <button
        onClick={onSplit}
        className="btn btn-ghost btn-sm"
        title="Split scene at playhead"
      >
        ✂ Split
      </button>
      <button
        onClick={onSkip}
        className={`btn btn-ghost btn-sm ${skipActive ? "text-[#6d5dfb]" : ""}`}
        title="Skip scene — kept on the timeline but jumped over on playback & render"
      >
        {skipActive ? "↩ Unskip" : "⤼ Skip"}
      </button>
      <button
        onClick={onDuplicate}
        className="btn btn-ghost btn-sm"
        title="Duplicate scene"
      >
        ⧉ Duplicate
      </button>
      <button
        onClick={onDelete}
        className="btn btn-ghost btn-sm"
        title="Delete scene"
      >
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
        {trailing}
      </div>
    </div>
  );
}

// Trim mode: a focused single track (video + waveform baked into each clip),
// swapped in for the full multi-row timeline — same inline editing, no popup.
// A layout item is one segment placed on the compressed (gap-free) effective
// timeline: `start`/`end` are effective ms, `idx` is its real index in spec.segments.
type TrimLayoutItem = {
  s: EditSegment;
  idx: number;
  start: number;
  end: number;
  d: number;
};

function TrimTrack({
  sectionRef,
  spec,
  source,
  cur,
  dur,
  activeIdx,
  tlZoom,
  setTlZoom,
  seekTo,
  onMoveBoundary,
  onFinalizeBoundary,
  onDelete,
  onDuplicate,
  onSkip,
  onSplit,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  onDone,
}: {
  sectionRef?: React.RefObject<HTMLElement>;
  spec: EditSpec;
  source: string | null;
  cur: number;
  dur: number;
  activeIdx: number;
  tlZoom: number;
  setTlZoom: (n: number) => void;
  seekTo: (s: number) => void;
  onMoveBoundary: (
    leftIdx: number | null,
    rightIdx: number | null,
    ms: number,
  ) => void;
  onFinalizeBoundary: (leftIdx: number | null, rightIdx: number | null) => void;
  onDelete: () => void;
  onDuplicate: () => void;
  onSkip: () => void;
  onSplit: () => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  onDone: () => void;
}) {
  const frames = useFilmstrip(source, 48);
  const peaks = useWaveform(source, 400);
  const trackRef = useRef<HTMLDivElement>(null);
  const skipActive = activeIdx >= 0 && !!spec.segments[activeIdx]?.skipped;
  const activeSeg = activeIdx >= 0 ? spec.segments[activeIdx] : null;

  // Pack every segment back-to-back in "effective" time — no gaps, even if the
  // source has silence between them — same feel as the old Trim popup.
  const layout = useMemo(() => {
    const sorted = spec.segments
      .map((s, idx) => ({ s, idx }))
      .sort((a, b) => a.s.source_start_ms - b.s.source_start_ms);
    let off = 0;
    const items: TrimLayoutItem[] = sorted.map(({ s, idx }) => {
      const d = Math.max(0, s.source_end_ms - s.source_start_ms);
      const it = { s, idx, start: off, end: off + d, d };
      off += d;
      return it;
    });
    return { items, total: Math.max(off, 1) };
  }, [spec.segments]);

  const effToItem = (eff: number) =>
    layout.items.find((it) => eff >= it.start && eff < it.end) ??
    layout.items[layout.items.length - 1] ??
    null;
  const effToSource = (eff: number) => {
    const it = effToItem(eff);
    return it ? it.s.source_start_ms + (eff - it.start) : 0;
  };
  const sourceToEff = (srcMs: number) => {
    const it =
      layout.items.find(
        (x) => srcMs >= x.s.source_start_ms && srcMs < x.s.source_end_ms,
      ) ?? [...layout.items].reverse().find((x) => x.s.source_end_ms <= srcMs);
    if (!it) return 0;
    return srcMs >= it.s.source_start_ms && srcMs < it.s.source_end_ms
      ? it.start + (srcMs - it.s.source_start_ms)
      : it.end;
  };
  const effAtClientX = (clientX: number) => {
    const r = trackRef.current?.getBoundingClientRect();
    if (!r) return 0;
    return (
      Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * layout.total
    );
  };

  // Scrub by dragging anywhere on the track background (not a block's edge handle).
  const scrubbing = useRef(false);
  const onTrackDown = (e: React.PointerEvent) => {
    scrubbing.current = true;
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    seekTo(effToSource(effAtClientX(e.clientX)) / 1000);
  };
  const onTrackMove = (e: React.PointerEvent) => {
    if (!scrubbing.current) return;
    seekTo(effToSource(effAtClientX(e.clientX)) / 1000);
  };
  const onTrackUp = () => {
    scrubbing.current = false;
  };

  const playheadPct = Math.min(
    100,
    (sourceToEff(cur * 1000) / layout.total) * 100,
  );

  return (
    <section
      ref={sectionRef}
      className="border-t border-[var(--border)] bg-[var(--card)] px-6 py-3"
    >
      <TimelineToolbar
        onUndo={onUndo}
        onRedo={onRedo}
        canUndo={canUndo}
        canRedo={canRedo}
        onSplit={onSplit}
        onSkip={onSkip}
        skipActive={skipActive}
        onDuplicate={onDuplicate}
        onDelete={onDelete}
        tlZoom={tlZoom}
        setTlZoom={setTlZoom}
        trailing={
          <button
            onClick={onDone}
            className="btn btn-ghost btn-sm text-[#6d5dfb]"
            title="Back to the full timeline"
          >
            ✓ Done trimming
          </button>
        }
      />

      {/* selection info */}
      <div className="mt-2 flex items-center gap-3 rounded-lg bg-[var(--hover)] px-3 py-1.5 text-xs">
        {activeSeg ? (
          <>
            <span className="font-semibold text-[var(--text)]">
              Block {activeIdx + 1}
            </span>
            <span className="font-mono text-[var(--text-2)]">
              {mmss(activeSeg.source_start_ms / 1000)} –{" "}
              {mmss(activeSeg.source_end_ms / 1000)}
            </span>
            <span className="font-mono text-[var(--text-2)]">
              ·{" "}
              {(
                (activeSeg.source_end_ms - activeSeg.source_start_ms) /
                1000
              ).toFixed(1)}
              s
            </span>
            {activeSeg.skipped && (
              <span className="badge bg-slate-200 text-slate-600">skipped</span>
            )}
            <span className="text-[var(--text-3)]">
              drag its side handles to adjust the range
            </span>
          </>
        ) : (
          <span className="text-[var(--text-3)]">
            No block selected — click a block to Split / Skip / Delete it, or
            drag the timeline to scrub.
          </span>
        )}
        <span className="ml-auto font-mono text-[var(--text-2)]">
          ▶ {mmss(cur)}
        </span>
      </div>

      {/* ruler */}
      <div className="relative mt-2 h-5 text-[10px] text-[var(--text-3)]">
        {Array.from({ length: 10 }).map((_, i) => (
          <span
            key={i}
            style={{ left: `${(i / 9) * 100}%` }}
            className="absolute -translate-x-1/2"
          >
            {mmss(((layout.total / 1000) * i) / 9)}
          </span>
        ))}
      </div>

      {/* single track — clips packed with no gaps, real footage + waveform baked into each one */}
      <div className="overflow-x-auto pb-2">
        <div
          ref={trackRef}
          data-track
          className="relative h-32 touch-none select-none rounded-lg bg-white ring-1 ring-inset ring-[var(--border)]"
          style={{ width: `${tlZoom * 100}%`, minWidth: "100%" }}
          onPointerDown={onTrackDown}
          onPointerMove={onTrackMove}
          onPointerUp={onTrackUp}
        >
          {layout.items.map((it, pos) => {
            const left = layout.items[pos - 1]?.idx ?? null;
            const right = layout.items[pos + 1]?.idx ?? null;
            return (
              <TrimBlock
                key={it.s.step_id}
                it={it}
                layoutTotal={layout.total}
                active={activeIdx === it.idx}
                skipped={!!it.s.skipped}
                frames={frames}
                peaks={peaks}
                dur={dur}
                curSrcMs={cur * 1000}
                onSeek={() => seekTo(it.s.source_start_ms / 1000)}
                onResizeStart={(ms) => onMoveBoundary(left, it.idx, ms)}
                onResizeEnd={(ms) => onMoveBoundary(it.idx, right, ms)}
                onFinalizeStart={() => onFinalizeBoundary(left, it.idx)}
                onFinalizeEnd={() => onFinalizeBoundary(it.idx, right)}
                effAtClientX={effAtClientX}
              />
            );
          })}
          {/* audio still decoding */}
          {peaks.length === 0 && (
            <span className="pointer-events-none absolute bottom-1 right-2 rounded bg-black/55 px-1.5 py-0.5 text-[10px] text-white/80">
              analyzing audio…
            </span>
          )}
          {/* draggable playhead */}
          {dur > 0 && (
            <span
              style={{ left: `${playheadPct}%` }}
              className="pointer-events-none absolute -top-1 bottom-0 w-0.5 -translate-x-1/2 bg-[#111827]"
            >
              <span className="absolute -top-1.5 left-1/2 h-3.5 w-3.5 -translate-x-1/2 rounded-full border-2 border-white bg-[#6d5dfb] shadow" />
            </span>
          )}
        </div>
      </div>
      <p className="mt-1 text-[11px] text-[var(--text-3)]">
        Drag the timeline to scrub. Click a block to select it — drag its side
        handles to trim the range; the neighboring clip follows so there's never
        a gap. Split / Skip / Duplicate / Delete act on the selected clip. Click
        "Done trimming" to return to the full timeline.
      </p>
    </section>
  );
}

function TrimBlock({
  it,
  layoutTotal,
  active,
  skipped,
  frames,
  peaks,
  dur,
  curSrcMs,
  onSeek,
  onResizeStart,
  onResizeEnd,
  onFinalizeStart,
  onFinalizeEnd,
  effAtClientX,
}: {
  it: TrimLayoutItem;
  layoutTotal: number;
  active: boolean;
  skipped: boolean;
  frames: Frame[];
  peaks: number[];
  dur: number;
  curSrcMs: number;
  onSeek: () => void;
  onResizeStart: (ms: number) => void;
  onResizeEnd: (ms: number) => void;
  onFinalizeStart: () => void;
  onFinalizeEnd: () => void;
  effAtClientX: (clientX: number) => number;
}) {
  const left = (it.start / layoutTotal) * 100;
  const width = Math.max(0.6, (it.d / layoutTotal) * 100);
  const text = eff(it.s);
  const blkFrames = framesInRange(
    frames,
    it.s.source_start_ms,
    it.s.source_end_ms,
  );
  const blkPeaks =
    dur > 0
      ? peaksInRange(peaks, dur, it.s.source_start_ms, it.s.source_end_ms)
      : [];
  const dragEdge = useRef<"l" | "r" | null>(null);

  const begin = (edge: "l" | "r") => (e: React.PointerEvent<HTMLElement>) => {
    e.stopPropagation();
    dragEdge.current = edge;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const move = (e: React.PointerEvent<HTMLElement>) => {
    if (!dragEdge.current) return;
    e.stopPropagation();
    // Anchor the drag to this block's own start — effective and source ms move
    // in lockstep within one block, so this maps the pointer straight to source ms.
    const ms = Math.round(
      it.s.source_start_ms + (effAtClientX(e.clientX) - it.start),
    );
    if (dragEdge.current === "l") onResizeStart(ms);
    else onResizeEnd(ms);
  };
  const end = (e: React.PointerEvent<HTMLElement>) => {
    e.stopPropagation();
    if (!dragEdge.current) return;
    if (dragEdge.current === "l") onFinalizeStart();
    else onFinalizeEnd();
    dragEdge.current = null;
  };

  return (
    <div
      onPointerUp={() => {
        if (!dragEdge.current) onSeek();
      }}
      style={{ left: `${left}%`, width: `${width}%` }}
      title={skipped ? `Skipped — ${text}` : text}
      className={`absolute top-0 h-full overflow-hidden rounded-md bg-[#0e1116] ring-1 ring-inset ${
        active ? "ring-2 ring-[#6d5dfb]" : "ring-black/20"
      }`}
    >
      {/* real frames */}
      <span className="absolute inset-0 flex">
        {blkFrames.length ? (
          blkFrames.map((f, i) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={i}
              src={f.url}
              alt=""
              draggable={false}
              className="h-full flex-1 object-cover"
              style={{ minWidth: 0 }}
            />
          ))
        ) : (
          <span className="h-full w-full bg-[var(--brand-2)]" />
        )}
      </span>
      {/* start time · duration chip */}
      {width > 5 && (
        <span className="pointer-events-none absolute left-1 top-1 z-10 rounded bg-black/60 px-1 py-px font-mono text-[9px] leading-snug text-white">
          {mmss(it.s.source_start_ms / 1000)} · {(it.d / 1000).toFixed(0)}s
        </span>
      )}
      {/* real audio peaks */}
      {blkPeaks.length > 0 && (
        <span className="absolute inset-x-0 bottom-0 flex h-10 items-end gap-[1px] bg-gradient-to-t from-black/85 via-black/50 to-transparent px-0.5 pb-0.5">
          {blkPeaks.map((p, i) => {
            const barSrc =
              it.s.source_start_ms +
              ((i + 0.5) / blkPeaks.length) *
                (it.s.source_end_ms - it.s.source_start_ms);
            return (
              <span
                key={i}
                className={`flex-1 rounded-t-sm ${barSrc <= curSrcMs ? "bg-[#8b7dff]" : "bg-white/30"}`}
                style={{ height: `${Math.max(2, p * 100)}%`, minWidth: 1 }}
              />
            );
          })}
        </span>
      )}
      {/* skipped overlay */}
      {skipped && (
        <span className="absolute inset-0 flex items-center justify-center bg-[repeating-linear-gradient(45deg,rgba(17,24,39,.55),rgba(17,24,39,.55)_6px,rgba(154,161,178,.55)_6px,rgba(154,161,178,.55)_12px)]">
          {width > 6 && (
            <span className="rounded bg-black/50 px-1 text-[10px] font-medium text-white">
              ⤼ skipped
            </span>
          )}
        </span>
      )}
      {active && (
        <>
          <span
            onPointerDown={begin("l")}
            onPointerMove={move}
            onPointerUp={end}
            title="Drag to adjust start"
            className="absolute inset-y-0 -left-1.5 z-10 flex w-4 cursor-ew-resize touch-none items-center justify-center rounded-l-md bg-[#6d5dfb] hover:bg-[#5b4ce6]"
          >
            <span className="h-6 w-0.5 rounded bg-white" />
          </span>
          <span
            onPointerDown={begin("r")}
            onPointerMove={move}
            onPointerUp={end}
            title="Drag to adjust end"
            className="absolute inset-y-0 -right-1.5 z-10 flex w-4 cursor-ew-resize touch-none items-center justify-center rounded-r-md bg-[#6d5dfb] hover:bg-[#5b4ce6]"
          >
            <span className="h-6 w-0.5 rounded bg-white" />
          </span>
        </>
      )}
    </div>
  );
}

// Crop mode: swaps the timeline into a focused track for assigning each crop
// region's time window (drag its block to move, side handles to resize) —
// the box itself is dragged/resized directly on the preview above.
function CropTrack({
  sectionRef,
  source,
  cur,
  dur,
  crops,
  cropSel,
  setCropSel,
  seekTo,
  onPatchCrop,
  onAddCrop,
  onRemoveCrop,
  onRemoveAll,
  onDone,
}: {
  sectionRef?: React.RefObject<HTMLElement>;
  source: string | null;
  cur: number;
  dur: number;
  crops: CropRegion[];
  cropSel: number;
  setCropSel: (n: number) => void;
  seekTo: (s: number) => void;
  onPatchCrop: (idx: number, patch: Partial<CropRegion>) => void;
  onAddCrop: () => void;
  onRemoveCrop: (idx: number) => void;
  onRemoveAll: () => void;
  onDone: () => void;
}) {
  const frames = useFilmstrip(source, 48);
  const stripRef = useRef<HTMLDivElement>(null);
  const totalMs = Math.max(dur * 1000, 1);
  const sel = Math.min(cropSel, Math.max(0, crops.length - 1));
  const box = crops[sel] as CropRegion | undefined;
  const dragRef = useRef<null | {
    mode: "seek" | "move" | "l" | "r";
    idx: number;
    grab: number;
  }>(null);

  const msAtX = (clientX: number) => {
    const r = stripRef.current?.getBoundingClientRect();
    if (!r) return 0;
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * totalMs;
  };
  const stripDown = (e: React.PointerEvent) => {
    dragRef.current = { mode: "seek", idx: -1, grab: 0 };
    e.currentTarget.setPointerCapture?.(e.pointerId);
    seekTo(msAtX(e.clientX) / 1000);
  };
  const blockDown = (
    e: React.PointerEvent,
    idx: number,
    mode: "move" | "l" | "r",
  ) => {
    e.stopPropagation();
    setCropSel(idx);
    dragRef.current = {
      mode,
      idx,
      grab: msAtX(e.clientX) - (crops[idx].start_ms ?? 0),
    };
    stripRef.current?.setPointerCapture?.(e.pointerId);
  };
  const stripMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    const at = msAtX(e.clientX);
    if (d.mode === "seek") {
      seekTo(at / 1000);
      return;
    }
    const c = crops[d.idx];
    if (!c) return;
    const s0 = c.start_ms ?? 0;
    const en = c.end_ms ?? 0;
    if (d.mode === "move") {
      const width = en - s0;
      const ns = Math.max(0, Math.min(at - d.grab, totalMs - width));
      onPatchCrop(d.idx, {
        start_ms: Math.round(ns),
        end_ms: Math.round(ns + width),
      });
    } else if (d.mode === "l") {
      onPatchCrop(d.idx, {
        start_ms: Math.round(Math.max(0, Math.min(at, en - 500))),
      });
    } else {
      onPatchCrop(d.idx, {
        end_ms: Math.round(Math.min(totalMs, Math.max(at, s0 + 500))),
      });
    }
  };
  const stripUp = () => {
    dragRef.current = null;
  };

  const rStart = box?.start_ms ?? 0;
  const rEnd = box?.end_ms ?? 0;
  const rangeOn = rEnd > rStart;

  return (
    <section
      ref={sectionRef}
      className="border-t border-[var(--border)] bg-[var(--card)] px-6 py-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        {crops.map((c, i) => {
          const ranged = (c.end_ms ?? 0) > (c.start_ms ?? 0);
          return (
            <span
              key={i}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs ${
                i === sel
                  ? "border-[#6d5dfb] bg-[#6d5dfb]/10 text-[var(--text)]"
                  : "border-[var(--border)] text-[var(--text-2)]"
              }`}
            >
              <button
                onClick={() => {
                  setCropSel(i);
                  if (ranged) seekTo((c.start_ms ?? 0) / 1000);
                }}
              >
                Crop {i + 1}
                <span className="ml-1 font-mono text-[10px] text-[var(--text-3)]">
                  {ranged
                    ? `${mmss((c.start_ms ?? 0) / 1000)}–${mmss((c.end_ms ?? 0) / 1000)}`
                    : "whole video"}
                </span>
              </button>
              {crops.length > 1 && (
                <button
                  title="Remove this crop"
                  onClick={() => onRemoveCrop(i)}
                  className="text-[var(--text-3)] hover:text-[var(--text)]"
                >
                  ×
                </button>
              )}
            </span>
          );
        })}
        <button onClick={onAddCrop} className="btn btn-ghost btn-sm">
          ＋ Add crop
        </button>
        {crops.length > 0 && (
          <button
            onClick={onRemoveAll}
            className="btn btn-ghost btn-sm text-[var(--text-2)]"
          >
            Remove all crops
          </button>
        )}
        <button
          onClick={onDone}
          className="btn btn-ghost btn-sm ml-auto text-[#6d5dfb]"
          title="Back to the full timeline"
        >
          ✓ Done cropping
        </button>
      </div>

      {box && (
        <div className="mt-2 rounded-xl border border-[var(--border)] p-3">
          <label className="flex cursor-pointer items-center justify-between">
            <span>
              <span className="text-sm font-medium">
                Crop {crops.length > 1 ? `${sel + 1} ` : ""}only a time range
              </span>
              <span className="mt-0.5 block text-xs text-[var(--text-3)]">
                Outside it the video stays uncropped — add another crop to cover
                it.
              </span>
            </span>
            <input
              type="checkbox"
              checked={rangeOn}
              onChange={(e) =>
                onPatchCrop(
                  sel,
                  e.target.checked
                    ? {
                        start_ms: Math.round(cur * 1000),
                        end_ms: Math.round(Math.min(dur, cur + 10) * 1000),
                      }
                    : { start_ms: 0, end_ms: 0 },
                )
              }
              className="h-4 w-8 accent-[#6d5dfb]"
            />
          </label>
          {/* filmstrip timeline — drag a crop window like a trim block */}
          <div
            ref={stripRef}
            onPointerDown={stripDown}
            onPointerMove={stripMove}
            onPointerUp={stripUp}
            className="relative mt-3 h-16 touch-none select-none overflow-hidden rounded-lg bg-[#0e1116] ring-1 ring-inset ring-[var(--border)]"
          >
            <Filmstrip frames={frames} className="opacity-70" />
            {crops.map((c, i) => {
              const s0 = c.start_ms ?? 0;
              const en = c.end_ms ?? 0;
              if (en <= s0) return null; // whole-video crop — no window to draw
              const left = (s0 / totalMs) * 100;
              const width = Math.max(0.5, ((en - s0) / totalMs) * 100);
              const active = i === sel;
              return (
                <div
                  key={i}
                  onPointerDown={(e) => blockDown(e, i, "move")}
                  style={{ left: `${left}%`, width: `${width}%` }}
                  title={`Crop ${i + 1} · ${mmss(s0 / 1000)}–${mmss(en / 1000)} — drag to move`}
                  className={`absolute inset-y-0 cursor-grab rounded-md border bg-[#6d5dfb]/30 backdrop-brightness-110 ${
                    active
                      ? "border-[#6d5dfb] ring-2 ring-inset ring-[#6d5dfb]"
                      : "border-white/40"
                  }`}
                >
                  {width > 7 && (
                    <span className="pointer-events-none absolute left-1.5 top-1 rounded bg-black/60 px-1 py-px font-mono text-[9px] text-white">
                      Crop {i + 1}
                    </span>
                  )}
                  {active && (
                    <>
                      <span
                        onPointerDown={(e) => blockDown(e, i, "l")}
                        title="Drag to adjust start"
                        className="absolute inset-y-0 -left-0.5 flex w-2.5 cursor-ew-resize items-center justify-center rounded-l-md bg-[#6d5dfb]"
                      >
                        <span className="h-6 w-0.5 rounded bg-white" />
                      </span>
                      <span
                        onPointerDown={(e) => blockDown(e, i, "r")}
                        title="Drag to adjust end"
                        className="absolute inset-y-0 -right-0.5 flex w-2.5 cursor-ew-resize items-center justify-center rounded-r-md bg-[#6d5dfb]"
                      >
                        <span className="h-6 w-0.5 rounded bg-white" />
                      </span>
                    </>
                  )}
                </div>
              );
            })}
            {/* playhead */}
            <span
              style={{
                left: `${Math.min(100, (cur * 1000 * 100) / totalMs)}%`,
              }}
              className="pointer-events-none absolute inset-y-0 w-px bg-white"
            />
          </div>
          <p className="mt-1.5 text-right font-mono text-[11px] text-[var(--text-3)]">
            {rangeOn
              ? `Crop ${crops.length > 1 ? sel + 1 : ""} applies ${mmss(rStart / 1000)} – ${mmss(rEnd / 1000)}`
              : "applies to the whole video"}
          </p>
        </div>
      )}
      <p className="mt-2 text-[11px] text-[var(--text-3)]">
        Drag the box on the video preview above to position or resize this crop.
        Click a chip to switch which region you're editing, or drag its block
        below to change when it applies. Click "Done cropping" when finished.
      </p>
    </section>
  );
}

function DraggableBlock({
  b,
  totalMs,
  active,
  skipped,
  onSeek,
  onMove,
  onResize,
  onResizeStart,
}: {
  b: { s: EditSegment; i: number; left: number; width: number; text: string };
  totalMs: number;
  active: boolean;
  skipped?: boolean;
  onSeek: () => void;
  onMove: (startMs: number) => void;
  onResize: (endMs: number) => void;
  onResizeStart: (startMs: number) => void;
}) {
  const drag = useRef<{
    mode: "move" | "resize" | "resize-start";
    startX: number;
    orig: number;
    trackW: number;
    moved: boolean;
  } | null>(null);

  const begin =
    (mode: "move" | "resize" | "resize-start") =>
    (e: React.PointerEvent<HTMLElement>) => {
      e.stopPropagation();
      const track = e.currentTarget.closest(
        "[data-track]",
      ) as HTMLElement | null;
      const trackW = track?.clientWidth || 1;
      drag.current = {
        mode,
        startX: e.clientX,
        orig:
          mode === "move" || mode === "resize-start"
            ? b.s.source_start_ms
            : b.s.source_end_ms,
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
    } else if (d.mode === "resize-start") {
      onResizeStart(
        Math.max(0, Math.min(d.orig + deltaMs, b.s.source_end_ms - 300)),
      );
    } else {
      onResize(
        Math.max(
          b.s.source_start_ms + 300,
          Math.min(d.orig + deltaMs, totalMs),
        ),
      );
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
      className={`group/blk absolute inset-y-0 flex cursor-grab items-end overflow-hidden rounded-md px-1 pb-0.5 text-[10px] font-medium text-white ring-1 ring-inset active:cursor-grabbing ${
        skipped
          ? "bg-[repeating-linear-gradient(45deg,rgba(17,24,39,.55),rgba(17,24,39,.55)_6px,rgba(154,161,178,.55)_6px,rgba(154,161,178,.55)_12px)] ring-[var(--border-strong)]"
          : "bg-[#6d5dfb]/10 ring-[#6d5dfb]/30 hover:bg-[#6d5dfb]/20"
      } ${active ? "ring-2 ring-[#6d5dfb]" : ""}`}
      title={skipped ? `Skipped — ${b.text}` : b.text}
    >
      <span className="pointer-events-none truncate rounded bg-black/45 px-1 leading-tight backdrop-blur-[1px]">
        {skipped ? "⤼ skipped" : b.text}
      </span>
      <span
        onPointerDown={begin("resize-start")}
        onPointerMove={move}
        onPointerUp={end}
        className="absolute left-0 top-0 h-full w-2 cursor-ew-resize rounded-l-md bg-[#6d5dfb]/50 opacity-0 transition-opacity group-hover/blk:opacity-100"
        title="Trim start"
      />
      <span
        onPointerDown={begin("resize")}
        onPointerMove={move}
        onPointerUp={end}
        className="absolute right-0 top-0 h-full w-2 cursor-ew-resize rounded-r-md bg-[#6d5dfb]/50 opacity-0 transition-opacity group-hover/blk:opacity-100"
        title="Trim end"
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
