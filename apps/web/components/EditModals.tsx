"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Rnd } from "react-rnd";
import { mediaUrl, type CropRegion, type EditSegment } from "@/lib/api";
import { Filmstrip, useFilmstrip, useWaveform, type Frame } from "@/lib/media";

const mmss = (t: number) =>
  Number.isFinite(t) && t >= 0
    ? `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`
    : "0:00";

/**
 * MediaRecorder WebM/blob videos often report `duration === Infinity` until the
 * browser is forced to seek to the end. Resolve the real duration, then reset
 * the playhead. Falls back gracefully if metadata is already valid.
 */
export function resolveDuration(video: HTMLVideoElement, set: (d: number) => void) {
  const d = video.duration;
  if (Number.isFinite(d) && d > 0) {
    set(d);
    return;
  }
  const onChange = () => {
    if (Number.isFinite(video.duration) && video.duration > 0) {
      video.removeEventListener("durationchange", onChange);
      video.currentTime = 0;
      set(video.duration);
    }
  };
  video.addEventListener("durationchange", onChange);
  // Nudge the browser to scan to the actual end so `duration` gets computed.
  video.currentTime = 1e7;
}

export function ModalShell({
  title,
  onClose,
  children,
  footer,
  maxWidth = "max-w-4xl",
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer: React.ReactNode;
  maxWidth?: string;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className={`flex max-h-[94vh] w-full flex-col overflow-hidden rounded-2xl bg-[var(--card)] shadow-2xl ${maxWidth}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4">
          <h2 className="text-lg font-semibold text-[var(--text)]">{title}</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-[var(--text-2)] hover:bg-[var(--hover)]">
            ✕
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-6">{children}</div>
        <div className="flex items-center gap-3 px-6 py-4">{footer}</div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Trim: block timeline with waveform — split at playhead, delete block */
/* ------------------------------------------------------------------ */
type TrimBlock = EditSegment & { _deleted?: boolean };

export function TrimModal({
  source,
  segments,
  onCancel,
  onSave,
}: {
  source: string;
  segments: EditSegment[];
  onCancel: () => void;
  onSave: (segs: EditSegment[]) => void;
}) {
  // Working blocks, ordered by source time. Deletions are marked (not dropped)
  // so the removed region can show as a white gap until the user saves.
  const [blocks, setBlocks] = useState<TrimBlock[]>(() =>
    [...segments].sort((a, b) => a.source_start_ms - b.source_start_ms).map((s) => ({ ...s })),
  );
  const [sel, setSel] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const [curEff, setCurEff] = useState(0); // playhead in *effective* (timeline) ms
  const [dur, setDur] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [zoom, setZoom] = useState(1);
  const frames = useFilmstrip(source, 48);
  const peaks = useWaveform(source, 400);

  // Real frames / audio peaks that fall inside a block's *source* time range.
  // A short block with no sampled frame gets its nearest neighbour, so every
  // block shows real footage instead of a flat color.
  const framesInRange = (a: number, b: number): Frame[] => {
    const inR = frames.filter((f) => f.t >= a - 1 && f.t <= b + 1);
    if (inR.length) return inR;
    const mid = (a + b) / 2;
    let nearest: Frame | null = null;
    for (const f of frames) if (!nearest || Math.abs(f.t - mid) < Math.abs(nearest.t - mid)) nearest = f;
    return nearest ? [nearest] : [];
  };
  const peaksInRange = (a: number, b: number): number[] => {
    const total = dur * 1000;
    if (!peaks.length || total <= 0) return [];
    const i0 = Math.max(0, Math.floor((a / total) * peaks.length));
    const i1 = Math.min(peaks.length, Math.ceil((b / total) * peaks.length));
    return peaks.slice(i0, i1);
  };

  // Lay blocks out contiguously in "effective" time: kept + deleted both take a
  // slot, so a fresh (contiguous) spec fills the bar fully with blue, and a
  // delete carves a white gap in place. On reopen only kept blocks arrive → full blue again.
  const layout = useMemo(() => {
    let off = 0;
    const items = blocks.map((b) => {
      const d = Math.max(0, b.source_end_ms - b.source_start_ms);
      const it = { b, start: off, end: off + d, d };
      off += d;
      return it;
    });
    return { items, total: Math.max(off, 1) };
  }, [blocks]);

  const keptMs = layout.items.reduce((a, it) => a + (it.b._deleted || it.b.skipped ? 0 : it.d), 0);
  const selIt = layout.items.find((it) => it.b.step_id === sel) ?? null;
  const selIdx = selIt ? layout.items.indexOf(selIt) : -1;
  const selDeleted = selIt?.b._deleted ?? false;

  const effToItem = (eff: number) =>
    layout.items.find((it) => eff >= it.start && eff < it.end) ?? layout.items[layout.items.length - 1] ?? null;
  const effToSource = (eff: number) => {
    const it = effToItem(eff);
    return it ? { it, source: it.b.source_start_ms + (eff - it.start) } : { it: null, source: 0 };
  };
  const effAtClientX = (clientX: number) => {
    const r = trackRef.current?.getBoundingClientRect();
    if (!r) return 0;
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * layout.total;
  };

  function togglePlay() {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      // If parked past the end, restart from the first kept block.
      if (curEff >= layout.total - 20) {
        const first = layout.items.find((it) => !it.b._deleted && !it.b.skipped);
        if (first) {
          v.currentTime = first.b.source_start_ms / 1000;
          setCurEff(first.start);
        }
      }
      void v.play();
    } else v.pause();
  }

  // Playback engine: keep the <video> (which holds the *original* footage) on the
  // kept blocks only — skip any deleted block or removed-source gap.
  function onFrame() {
    const v = videoRef.current;
    if (!v) return;
    const t = v.currentTime * 1000; // source ms
    const here = layout.items.find((it) => t + 1 >= it.b.source_start_ms && t < it.b.source_end_ms);
    if (here && !here.b._deleted && !here.b.skipped) {
      setCurEff(here.start + (t - here.b.source_start_ms));
      return;
    }
    // Inside a deleted/skipped block or a removed gap → jump to the next kept block.
    const from = here ? here.b.source_end_ms : t;
    const next = layout.items.find((it) => !it.b._deleted && !it.b.skipped && it.b.source_start_ms >= from - 1);
    if (next) {
      v.currentTime = next.b.source_start_ms / 1000;
      setCurEff(next.start);
    } else {
      v.pause();
      setCurEff(layout.total);
    }
  }

  function scrubTo(eff: number) {
    setCurEff(eff);
    const { source } = effToSource(eff);
    if (videoRef.current) videoRef.current.currentTime = Math.max(0, Math.min(source / 1000, dur || source / 1000));
  }

  // Drag a block edge to reduce/expand its time range. Dragging the boundary
  // shared with an adjacent kept block redistributes time between the two;
  // against a gap/edge it trims that block only.
  const durOf = (b: TrimBlock) => Math.max(0, b.source_end_ms - b.source_start_ms);
  const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(Math.max(lo, hi), v));
  const resize = useRef<{ id: string; edge: "l" | "r" } | null>(null);
  const MIN_MS = 120;

  function beginResize(e: React.PointerEvent, id: string, edge: "l" | "r") {
    e.stopPropagation();
    resize.current = { id, edge };
    setSel(id);
    trackRef.current?.setPointerCapture?.(e.pointerId);
  }

  function doResize(clientX: number) {
    const rz = resize.current;
    if (!rz) return;
    const eff = effAtClientX(clientX);
    setBlocks((arr) => {
      const i = arr.findIndex((b) => b.step_id === rz.id);
      if (i < 0) return arr;
      let off = 0;
      for (let k = 0; k < i; k++) off += durOf(arr[k]);
      const b = arr[i];
      const maxMs = dur * 1000 || b.source_end_ms;
      const out = [...arr];
      if (rz.edge === "r") {
        const next = arr[i + 1];
        const coupled = next && !next._deleted && Math.abs(next.source_start_ms - b.source_end_ms) < 3;
        let end = Math.round(b.source_start_ms + (eff - off));
        if (coupled) {
          end = clamp(end, b.source_start_ms + MIN_MS, next.source_end_ms - MIN_MS);
          out[i] = { ...b, source_end_ms: end };
          out[i + 1] = { ...next, source_start_ms: end };
        } else {
          const cap = next && !next._deleted ? next.source_start_ms : maxMs;
          end = clamp(end, b.source_start_ms + MIN_MS, cap);
          out[i] = { ...b, source_end_ms: end };
        }
      } else {
        const prev = arr[i - 1];
        const coupled = prev && !prev._deleted && Math.abs(prev.source_end_ms - b.source_start_ms) < 3;
        if (coupled) {
          const offPrev = off - durOf(prev);
          let start = Math.round(prev.source_start_ms + (eff - offPrev));
          start = clamp(start, prev.source_start_ms + MIN_MS, b.source_end_ms - MIN_MS);
          out[i] = { ...b, source_start_ms: start };
          out[i - 1] = { ...prev, source_end_ms: start };
        } else {
          const floor = prev && !prev._deleted ? prev.source_end_ms : 0;
          let start = Math.round(b.source_start_ms + (eff - off));
          start = clamp(start, floor, b.source_end_ms - MIN_MS);
          out[i] = { ...b, source_start_ms: start };
        }
      }
      return out;
    });
    // preview the frame under the dragged edge
    const { source } = effToSource(eff);
    if (videoRef.current) videoRef.current.currentTime = clamp(source / 1000, 0, dur || source / 1000);
    setCurEff(Math.max(0, Math.min(eff, layout.total)));
  }

  // Re-split words across a resized boundary so captions/voice stay aligned.
  function finalizeResize() {
    const rz = resize.current;
    if (!rz) return;
    setBlocks((arr) => {
      const i = arr.findIndex((b) => b.step_id === rz.id);
      if (i < 0) return arr;
      const [ai, bi] = rz.edge === "r" ? [i, i + 1] : [i - 1, i];
      const A = arr[ai];
      const B = arr[bi];
      if (!A || !B || A._deleted || B._deleted || Math.abs(A.source_end_ms - B.source_start_ms) >= 3) return arr;
      const words = [...A.words, ...B.words];
      const removed = [...A.removed, ...B.removed.map((r) => r + A.words.length)];
      const frac = durOf(A) / Math.max(1, durOf(A) + durOf(B));
      const wi = Math.round(words.length * frac);
      const out = [...arr];
      out[ai] = { ...A, words: words.slice(0, wi), removed: removed.filter((r) => r < wi) };
      out[bi] = { ...B, words: words.slice(wi), removed: removed.filter((r) => r >= wi).map((r) => r - wi) };
      return out;
    });
  }

  // Pointer scrubbing on the timeline. A click without drag selects the block
  // under the cursor; a drag scrubs the playhead.
  const dragging = useRef(false);
  const moved = useRef(false);
  function onPointerDown(e: React.PointerEvent) {
    if (resize.current) return;
    dragging.current = true;
    moved.current = false;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    scrubTo(effAtClientX(e.clientX));
  }
  function onPointerMove(e: React.PointerEvent) {
    if (resize.current) {
      doResize(e.clientX);
      return;
    }
    if (!dragging.current) return;
    moved.current = true;
    scrubTo(effAtClientX(e.clientX));
  }
  function onPointerUp(e: React.PointerEvent) {
    if (resize.current) {
      finalizeResize();
      resize.current = null;
      return;
    }
    if (!dragging.current) return;
    dragging.current = false;
    if (!moved.current) {
      const it = effToItem(effAtClientX(e.clientX));
      if (it) setSel((p) => (p === it.b.step_id ? null : it.b.step_id));
    }
  }

  // Split the block under the playhead into two (words split proportionally).
  function splitAtPlayhead() {
    const { it, source } = effToSource(curEff);
    if (!it) return;
    const at = Math.round(source);
    if (at <= it.b.source_start_ms + 150 || at >= it.b.source_end_ms - 150) return;
    setBlocks((arr) => {
      const idx = arr.findIndex((b) => b.step_id === it.b.step_id);
      if (idx < 0) return arr;
      const seg = arr[idx];
      const frac = (at - seg.source_start_ms) / (seg.source_end_ms - seg.source_start_ms);
      const wi = Math.round(seg.words.length * frac);
      const a: TrimBlock = {
        ...seg,
        source_end_ms: at,
        words: seg.words.slice(0, wi),
        removed: seg.removed.filter((r) => r < wi),
      };
      const b: TrimBlock = {
        ...seg,
        step_id: `split_${idx}_${at}`,
        source_start_ms: at,
        words: seg.words.slice(wi),
        removed: seg.removed.filter((r) => r >= wi).map((r) => r - wi),
      };
      const out = [...arr];
      out.splice(idx, 1, a, b);
      return out;
    });
  }

  // Delete / restore the selected block (toggles the white gap).
  function toggleDeleteSelected() {
    if (!sel) return;
    setBlocks((arr) => arr.map((b) => (b.step_id === sel ? { ...b, _deleted: !b._deleted } : b)));
  }

  // Skip / unskip the selected block: kept in place (greyed), excluded from render.
  function toggleSkipSelected() {
    if (!sel) return;
    setBlocks((arr) => arr.map((b) => (b.step_id === sel ? { ...b, skipped: !b.skipped } : b)));
  }
  const selSkipped = layout.items.find((it) => it.b.step_id === sel)?.b.skipped ?? false;

  function save() {
    onSave(
      blocks
        .filter((b) => !b._deleted)
        .map(({ _deleted, ...seg }) => seg),
    );
  }

  const ticks = 9;
  const playheadPct = Math.min(100, (curEff / layout.total) * 100);
  const curSrc = effToSource(curEff).source; // playhead in SOURCE ms — lights the waveform

  return (
    <ModalShell
      title="Trim"
      onClose={onCancel}
      maxWidth="max-w-[96vw]"
      footer={
        <>
          <span className="text-sm text-[var(--text-2)]">Total duration: {mmss(keptMs / 1000)} min</span>
          <div className="ml-auto flex items-center gap-2">
            <button onClick={onCancel} className="btn btn-secondary">
              Cancel
            </button>
            <button onClick={save} className="btn btn-primary">
              Save changes
            </button>
          </div>
        </>
      }
    >
      {/* video — sized to its own aspect (no full-width black bars); kept modest
          so the editing timeline below gets the workspace */}
      <div className="flex items-center justify-center">
        <video
          ref={videoRef}
          src={mediaUrl(source)}
          className="max-h-[38vh] w-auto rounded-xl bg-black shadow"
          onLoadedMetadata={(e) => resolveDuration(e.currentTarget, setDur)}
          onTimeUpdate={onFrame}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />
      </div>

      {/* controls row */}
      <div className="mt-3 flex items-center gap-2">
        <button
          onClick={splitAtPlayhead}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm text-[var(--text)] hover:bg-[var(--hover)]"
        >
          ✂ Split at {mmss(curEff / 1000)}
        </button>
        <button
          onClick={toggleSkipSelected}
          disabled={!sel}
          className={`inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm hover:bg-[var(--hover)] disabled:opacity-40 ${
            selSkipped ? "text-[#6d5dfb]" : "text-[var(--text)]"
          }`}
          title="Skip — keeps the block in place but excludes it from playback & render"
        >
          {selSkipped ? "↩ Unskip Block" : "⤼ Skip Block"}
        </button>
        <button
          onClick={toggleDeleteSelected}
          disabled={!sel}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm text-[var(--text)] hover:bg-[var(--hover)] disabled:opacity-40"
        >
          {selDeleted ? "↩ Restore Block" : "🗑 Delete Block"}
        </button>
        <div className="mx-auto flex items-center gap-2">
          <button
            onClick={togglePlay}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-[#6d5dfb] text-xs text-white"
          >
            {playing ? "❚❚" : "▶"}
          </button>
          <span className="font-mono text-xs text-[var(--text-2)]">
            {mmss(curEff / 1000)} / {mmss(layout.total / 1000)}
          </span>
        </div>
        <span className="text-xs text-[var(--text-3)]">Zoom</span>
        <input
          type="range"
          min={1}
          max={4}
          step={0.5}
          value={zoom}
          onChange={(e) => setZoom(Number(e.target.value))}
          className="w-24 accent-[#6d5dfb]"
        />
      </div>

      {/* selection info — which block, its time range and duration */}
      <div className="mt-2 flex items-center gap-3 rounded-lg bg-[var(--hover)] px-3 py-1.5 text-xs">
        {selIt ? (
          <>
            <span className="font-semibold text-[var(--text)]">Block {selIdx + 1}</span>
            <span className="font-mono text-[var(--text-2)]">
              {mmss(selIt.b.source_start_ms / 1000)} – {mmss(selIt.b.source_end_ms / 1000)}
            </span>
            <span className="font-mono text-[var(--text-2)]">· {(selIt.d / 1000).toFixed(1)}s</span>
            {selIt.b.skipped && <span className="badge bg-slate-200 text-slate-600">skipped</span>}
            {selIt.b._deleted && <span className="badge bg-red-100 text-red-600">deleted</span>}
            <span className="text-[var(--text-3)]">drag its side handles to adjust the range</span>
          </>
        ) : (
          <span className="text-[var(--text-3)]">
            No block selected — click a block to Split / Skip / Delete it, or drag the timeline to scrub.
          </span>
        )}
        <span className="ml-auto font-mono text-[var(--text-2)]">▶ {mmss(curEff / 1000)}</span>
      </div>

      {/* block timeline */}
      <div className="mt-3 overflow-x-auto pb-2">
        <div style={{ width: `${zoom * 100}%`, minWidth: "100%" }}>
          {/* ruler */}
          <div className="relative h-5 text-[10px] text-[var(--text-3)]">
            {Array.from({ length: ticks + 1 }).map((_, i) => (
              <span key={i} style={{ left: `${(i / ticks) * 100}%` }} className="absolute -translate-x-1/2">
                {mmss(((layout.total / 1000) * i) / ticks)}
              </span>
            ))}
          </div>
          {/* blocks with waveform — white background shows through deleted gaps */}
          <div
            ref={trackRef}
            className="relative h-32 touch-none select-none rounded-lg bg-white ring-1 ring-inset ring-[var(--border)]"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
          >
            {layout.items.map((it) => {
              const left = (it.start / layout.total) * 100;
              const width = Math.max(0.6, (it.d / layout.total) * 100);
              const active = sel === it.b.step_id;
              const blkFrames = framesInRange(it.b.source_start_ms, it.b.source_end_ms);
              const blkPeaks = peaksInRange(it.b.source_start_ms, it.b.source_end_ms);
              if (it.b._deleted) {
                return (
                  <div
                    key={it.b.step_id}
                    style={{ left: `${left}%`, width: `${width}%` }}
                    title="Removed — click Restore Block to bring it back"
                    className={`absolute top-0 flex h-full items-center justify-center overflow-hidden rounded-md border border-dashed bg-[repeating-linear-gradient(45deg,#f4f5fa,#f4f5fa_6px,#e9ebf3_6px,#e9ebf3_12px)] ${
                      active ? "border-[#6d5dfb] ring-2 ring-[#6d5dfb]" : "border-[var(--border-strong)]"
                    }`}
                  >
                    {width > 6 && <span className="text-[10px] font-medium text-[var(--text-3)]">removed</span>}
                  </div>
                );
              }
              return (
                <div
                  key={it.b.step_id}
                  style={{ left: `${left}%`, width: `${width}%` }}
                  title={it.b.skipped ? `Skipped — ${it.b.words.slice(0, 8).join(" ")}` : it.b.words.slice(0, 8).join(" ")}
                  className={`absolute top-0 h-full overflow-hidden rounded-md bg-[#0e1116] ring-1 ring-inset ${
                    active ? "ring-2 ring-[#6d5dfb]" : "ring-black/20"
                  }`}
                >
                  {/* real frames */}
                  <span className="absolute inset-0 flex">
                    {blkFrames.length ? (
                      blkFrames.map((f, i) => (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img key={i} src={f.url} alt="" draggable={false} className="h-full flex-1 object-cover" style={{ minWidth: 0 }} />
                      ))
                    ) : (
                      <span className="h-full w-full bg-[var(--brand-2)]" />
                    )}
                  </span>
                  {/* start time · duration chip */}
                  {width > 5 && (
                    <span className="pointer-events-none absolute left-1 top-1 z-10 rounded bg-black/60 px-1 py-px font-mono text-[9px] leading-snug text-white">
                      {mmss(it.b.source_start_ms / 1000)} · {(it.d / 1000).toFixed(0)}s
                    </span>
                  )}
                  {/* real audio peaks — a waveform lane along the bottom. Bars light
                      up as playback passes them (played = purple, upcoming = faint);
                      silence stays flat so the spoken stretches stand out. */}
                  {blkPeaks.length > 0 && (
                    <span className="absolute inset-x-0 bottom-0 flex h-10 items-end gap-[1px] bg-gradient-to-t from-black/85 via-black/50 to-transparent px-0.5 pb-0.5">
                      {blkPeaks.map((p, i) => {
                        const barSrc =
                          it.b.source_start_ms +
                          ((i + 0.5) / blkPeaks.length) * (it.b.source_end_ms - it.b.source_start_ms);
                        return (
                          <span
                            key={i}
                            className={`flex-1 rounded-t-sm ${barSrc <= curSrc ? "bg-[#8b7dff]" : "bg-white/30"}`}
                            style={{ height: `${Math.max(2, p * 100)}%`, minWidth: 1 }}
                          />
                        );
                      })}
                    </span>
                  )}
                  {/* skipped overlay */}
                  {it.b.skipped && (
                    <span className="absolute inset-0 flex items-center justify-center bg-[repeating-linear-gradient(45deg,rgba(17,24,39,.55),rgba(17,24,39,.55)_6px,rgba(154,161,178,.55)_6px,rgba(154,161,178,.55)_12px)]">
                      {width > 6 && <span className="rounded bg-black/50 px-1 text-[10px] font-medium text-white">⤼ skipped</span>}
                    </span>
                  )}
                  {active && (
                    <>
                      <span
                        onPointerDown={(e) => beginResize(e, it.b.step_id, "l")}
                        title="Drag to adjust start"
                        className="absolute inset-y-0 -left-1.5 z-10 flex w-4 cursor-ew-resize touch-none items-center justify-center rounded-l-md bg-[#6d5dfb] hover:bg-[#5b4ce6]"
                      >
                        <span className="h-6 w-0.5 rounded bg-white" />
                      </span>
                      <span
                        onPointerDown={(e) => beginResize(e, it.b.step_id, "r")}
                        title="Drag to adjust end"
                        className="absolute inset-y-0 -right-1.5 z-10 flex w-4 cursor-ew-resize touch-none items-center justify-center rounded-r-md bg-[#6d5dfb] hover:bg-[#5b4ce6]"
                      >
                        <span className="h-6 w-0.5 rounded bg-white" />
                      </span>
                    </>
                  )}
                </div>
              );
            })}
            {/* audio still decoding — the waveform lane appears when it's ready */}
            {peaks.length === 0 && (
              <span className="pointer-events-none absolute bottom-1 right-2 rounded bg-black/55 px-1.5 py-0.5 text-[10px] text-white/80">
                analyzing audio…
              </span>
            )}
            {/* draggable playhead */}
            <span
              style={{ left: `${playheadPct}%` }}
              className="pointer-events-none absolute -top-1 bottom-0 w-0.5 -translate-x-1/2 bg-[#111827]"
            >
              <span className="absolute -top-1.5 left-1/2 h-3.5 w-3.5 -translate-x-1/2 rounded-full border-2 border-white bg-[#6d5dfb] shadow" />
            </span>
          </div>
        </div>
      </div>
      <p className="mt-1 text-[11px] text-[var(--text-3)]">
        Drag the timeline to scrub. Click a block to select it — drag its side handles to shrink/expand the time range,
        Split at the playhead to cut it in two, Skip Block to grey it out (kept in place, excluded from the render), or
        Delete Block (removed parts turn white and are dropped on save).
      </p>
    </ModalShell>
  );
}

/* ------------------------------------------------------------------ */
/* Range trim (pre-processing): drag In/Out handles on a waveform      */
/* ------------------------------------------------------------------ */
export function RangeTrimModal({
  source,
  initialStartMs = 0,
  initialEndMs = 0,
  onCancel,
  onSave,
}: {
  source: string;
  initialStartMs?: number;
  initialEndMs?: number;
  onCancel: () => void;
  onSave: (startMs: number, endMs: number) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const stripRef = useRef<HTMLDivElement>(null);
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [inMs, setInMs] = useState(initialStartMs);
  const [outMs, setOutMs] = useState(initialEndMs);
  const drag = useRef<null | "in" | "out">(null);
  const peaks = useWaveform(source, 300); // real voice amplitudes

  const totalMs = Math.max(dur * 1000, outMs, 1);
  const effOut = outMs || totalMs;

  function posToMs(clientX: number) {
    const r = stripRef.current?.getBoundingClientRect();
    if (!r) return 0;
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * totalMs;
  }
  function onDown(e: React.PointerEvent) {
    if (drag.current) return; // a handle grabbed the pointer first
    // click/drag on the strip itself scrubs the playhead to that time
    const v = videoRef.current;
    if (v) v.currentTime = Math.max(0, Math.min(posToMs(e.clientX) / 1000, dur || 0));
  }
  function onMove(e: React.PointerEvent) {
    if (!drag.current) {
      if (e.buttons === 1) onDown(e); // drag-to-scrub
      return;
    }
    const ms = posToMs(e.clientX);
    if (drag.current === "in") setInMs(Math.min(ms, effOut - 500));
    else setOutMs(Math.max(ms, inMs + 500));
  }

  const L = (inMs / totalMs) * 100;
  const R = (effOut / totalMs) * 100;

  return (
    <ModalShell
      title="Trim"
      onClose={onCancel}
      footer={
        <>
          <span className="text-sm text-[var(--text-2)]">
            Keeps {mmss((effOut - inMs) / 1000)} of {mmss(totalMs / 1000)} min
          </span>
          <div className="ml-auto flex items-center gap-2">
            <button onClick={onCancel} className="btn btn-secondary">
              Cancel
            </button>
            <button onClick={() => onSave(Math.round(inMs), Math.round(effOut))} className="btn btn-primary">
              Save changes
            </button>
          </div>
        </>
      }
    >
      <div className="overflow-hidden rounded-xl bg-black">
        <video
          ref={videoRef}
          src={mediaUrl(source)}
          className="mx-auto max-h-[46vh] w-auto"
          onLoadedMetadata={(e) => resolveDuration(e.currentTarget, setDur)}
          onTimeUpdate={(e) => setCur(e.currentTarget.currentTime)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />
      </div>

      <div className="mt-3 flex items-center justify-center gap-3">
        <button
          onClick={() => {
            const v = videoRef.current;
            if (!v) return;
            if (v.paused) void v.play();
            else v.pause();
          }}
          className="flex h-8 w-8 items-center justify-center rounded-full bg-[#6d5dfb] text-xs text-[var(--text)]"
        >
          {playing ? "❚❚" : "▶"}
        </button>
        <span className="font-mono text-xs text-[var(--text-2)]">
          {mmss(cur)} / {mmss(dur)}
        </span>
      </div>

      {/* waveform strip with drag handles — click anywhere to jump to that time */}
      <div
        ref={stripRef}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={() => (drag.current = null)}
        className="relative mt-3 h-16 cursor-pointer touch-none select-none overflow-hidden rounded-lg bg-[var(--hover)]"
      >
        {/* real voice waveform */}
        <span className="flex h-full items-center gap-[1px] px-1.5">
          {(peaks.length ? peaks : Array.from({ length: 140 }, () => 0.15)).map((p, i) => (
            <span
              key={i}
              className="flex-1 rounded bg-[var(--brand-2)]/80"
              style={{ height: `${Math.max(8, p * 82)}%`, minWidth: 1 }}
            />
          ))}
        </span>
        {/* dim removed ranges */}
        <div className="absolute inset-y-0 left-0 bg-white/75" style={{ width: `${L}%` }} />
        <div className="absolute inset-y-0 right-0 bg-white/75" style={{ width: `${100 - R}%` }} />
        {/* kept-range border */}
        <div
          className="pointer-events-none absolute inset-y-0 border-y-2 border-[#6d5dfb]"
          style={{ left: `${L}%`, width: `${R - L}%` }}
        />
        {/* handles */}
        {(
          [
            ["in", L],
            ["out", R],
          ] as const
        ).map(([which, pct]) => (
          <div
            key={which}
            onPointerDown={(e) => {
              drag.current = which;
              (e.currentTarget.parentElement as HTMLElement).setPointerCapture(e.pointerId);
            }}
            style={{ left: `${pct}%` }}
            className="absolute inset-y-0 z-10 flex w-3 -translate-x-1/2 cursor-ew-resize items-center justify-center rounded bg-[#6d5dfb]"
          >
            <span className="h-6 w-0.5 rounded bg-white/80" />
          </div>
        ))}
        {/* playhead */}
        <span
          style={{ left: `${Math.min(100, (cur * 1000 * 100) / totalMs)}%` }}
          className="pointer-events-none absolute inset-y-0 w-0.5 bg-[var(--text)]"
        />
      </div>
      <p className="mt-1 text-[11px] text-[var(--text-3)]">
        Drag the purple handles to choose which part of the recording to keep. Click anywhere on the waveform to jump
        the playhead to that time.
      </p>
    </ModalShell>
  );
}

/* ------------------------------------------------------------------ */
/* Raw block trim (pre-processing): split the video into blocks, delete */
/* ------------------------------------------------------------------ */
export function RawTrimModal({
  source,
  initialRanges,
  onCancel,
  onSave,
}: {
  source: string;
  initialRanges?: number[][]; // [[startMs,endMs], …] to seed
  onCancel: () => void;
  onSave: (ranges: number[][]) => void; // kept ranges in ms
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [dur, setDur] = useState(0);
  const [cur, setCur] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [blocks, setBlocks] = useState<{ id: string; start: number; end: number }[]>(
    (initialRanges && initialRanges.length ? initialRanges : []).map((r, i) => ({ id: `b${i}`, start: r[0], end: r[1] })),
  );
  const [sel, setSel] = useState<string | null>(null);
  const seeded = useRef(blocks.length > 0);

  // seed one block spanning the whole video once its (real) duration is known
  function onMeta() {
    const v = videoRef.current;
    if (!v) return;
    resolveDuration(v, (d) => {
      setDur(d);
      if (!seeded.current && d > 0) {
        setBlocks([{ id: "b0", start: 0, end: Math.round(d * 1000) }]);
        seeded.current = true;
      }
    });
  }

  const totalMs = Math.max(dur * 1000, 1);
  const keptMs = blocks.reduce((a, b) => a + (b.end - b.start), 0);
  const peaks = useWaveform(source, 400); // real voice amplitudes, not a pattern
  const frames = useFilmstrip(source, 32);

  // Playback engine: keep the playhead on KEPT blocks only — a deleted (white)
  // area is jumped over instead of playing through.
  function onFrame(e: React.SyntheticEvent<HTMLVideoElement>) {
    const v = e.currentTarget;
    const t = v.currentTime * 1000;
    setCur(v.currentTime);
    if (v.paused) return;
    const here = blocks.find((b) => t + 1 >= b.start && t < b.end);
    if (here) return; // inside a kept block — play on
    const next = [...blocks].sort((a, b) => a.start - b.start).find((b) => b.start >= t - 1);
    if (next) {
      v.currentTime = next.start / 1000;
    } else {
      v.pause();
      const first = [...blocks].sort((a, b) => a.start - b.start)[0];
      if (first) v.currentTime = first.start / 1000;
    }
  }
  const peaksIn = (a: number, b: number): number[] => {
    if (!peaks.length || totalMs <= 1) return [];
    const i0 = Math.max(0, Math.floor((a / totalMs) * peaks.length));
    const i1 = Math.min(peaks.length, Math.ceil((b / totalMs) * peaks.length));
    return peaks.slice(i0, i1);
  };

  function seek(sec: number) {
    if (videoRef.current) videoRef.current.currentTime = Math.max(0, Math.min(sec, dur || sec));
  }

  // Timeline scrubbing: drag anywhere to move the playhead; a plain click seeks
  // to that exact time AND toggles selection of the block under the cursor.
  const stripRef = useRef<HTMLDivElement>(null);
  const scrubbing = useRef(false);
  const scrubMoved = useRef(false);
  const msAtX = (clientX: number) => {
    const r = stripRef.current?.getBoundingClientRect();
    if (!r) return 0;
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * totalMs;
  };
  function stripDown(e: React.PointerEvent) {
    scrubbing.current = true;
    scrubMoved.current = false;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    seek(msAtX(e.clientX) / 1000);
  }
  function stripMove(e: React.PointerEvent) {
    if (!scrubbing.current) return;
    scrubMoved.current = true;
    seek(msAtX(e.clientX) / 1000);
  }
  function stripUp(e: React.PointerEvent) {
    if (!scrubbing.current) return;
    scrubbing.current = false;
    if (!scrubMoved.current) {
      const at = msAtX(e.clientX);
      const b = blocks.find((x) => at >= x.start && at < x.end);
      setSel((p) => (b && p !== b.id ? b.id : null));
    }
  }
  function splitAtPlayhead() {
    const at = cur * 1000;
    setBlocks((arr) => {
      const idx = arr.findIndex((b) => at > b.start + 200 && at < b.end - 200);
      if (idx < 0) return arr;
      const b = arr[idx];
      const out = [...arr];
      out.splice(idx, 1, { ...b, end: Math.round(at) }, { id: `b${Date.now()}`, start: Math.round(at), end: b.end });
      return out;
    });
  }
  function deleteSel() {
    if (!sel) return;
    setBlocks((arr) => arr.filter((b) => b.id !== sel));
    setSel(null);
  }

  return (
    <ModalShell
      title="Trim"
      onClose={onCancel}
      maxWidth="max-w-6xl"
      footer={
        <>
          <span className="text-sm text-[#6b7280]">Keeps {mmss(keptMs / 1000)} of {mmss(totalMs / 1000)} min</span>
          <div className="ml-auto flex items-center gap-2">
            <button onClick={onCancel} className="btn btn-secondary">
              Cancel
            </button>
            <button
              onClick={() => onSave([...blocks].sort((a, b) => a.start - b.start).map((b) => [b.start, b.end]))}
              className="btn btn-primary"
            >
              Save changes
            </button>
          </div>
        </>
      }
    >
      {/* video — sized to its own aspect (no full-width black bars); playback skips deleted areas */}
      <div className="flex items-center justify-center">
        <video
          ref={videoRef}
          src={mediaUrl(source)}
          className="max-h-[52vh] w-auto rounded-xl bg-black shadow"
          onLoadedMetadata={() => onMeta()}
          onTimeUpdate={onFrame}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />
      </div>

      {/* actions */}
      <div className="mt-3 flex items-center gap-2">
        <button onClick={splitAtPlayhead} className="inline-flex items-center gap-1.5 rounded-lg border border-[#eceef5] bg-white px-3 py-1.5 text-sm text-[#111827] hover:bg-[#f4f5fa]">
          ✂ Split at {mmss(cur)}
        </button>
        <button onClick={deleteSel} disabled={!sel} className="inline-flex items-center gap-1.5 rounded-lg border border-[#eceef5] bg-white px-3 py-1.5 text-sm text-[#111827] hover:bg-[#f4f5fa] disabled:opacity-40">
          🗑 Delete Block
        </button>
        <div className="mx-auto flex items-center gap-2">
          <button
            onClick={() => {
              const v = videoRef.current;
              if (!v) return;
              if (v.paused) void v.play();
              else v.pause();
            }}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-[#6d5dfb] text-xs text-white"
          >
            {playing ? "❚❚" : "▶"}
          </button>
          <span className="font-mono text-xs text-[#6b7280]">{mmss(cur)} / {mmss(dur)}</span>
        </div>
      </div>

      {/* block timeline — click/drag anywhere to pick a playback time */}
      <div
        ref={stripRef}
        onPointerDown={stripDown}
        onPointerMove={stripMove}
        onPointerUp={stripUp}
        className="relative mt-3 h-24 cursor-pointer touch-none select-none overflow-hidden rounded-lg bg-[#f4f5fa] ring-1 ring-inset ring-[var(--border)]"
      >
        {blocks.map((b) => {
          const left = (b.start / totalMs) * 100;
          const width = Math.max(0.8, ((b.end - b.start) / totalMs) * 100);
          const active = sel === b.id;
          const blkPeaks = peaksIn(b.start, b.end);
          const blkFrames = (() => {
            const inR = frames.filter((f) => f.t >= b.start - 1 && f.t <= b.end + 1);
            if (inR.length) return inR;
            const mid = (b.start + b.end) / 2;
            let nearest: Frame | null = null;
            for (const f of frames) if (!nearest || Math.abs(f.t - mid) < Math.abs(nearest.t - mid)) nearest = f;
            return nearest ? [nearest] : [];
          })();
          return (
            <div
              key={b.id}
              style={{ left: `${left}%`, width: `${width}%` }}
              className={`pointer-events-none absolute top-0 h-full overflow-hidden rounded-md bg-[#0e1116] ring-1 ring-inset ${
                active ? "ring-2 ring-[#6d5dfb]" : "ring-black/20"
              }`}
            >
              {/* real frames */}
              <span className="absolute inset-0 flex">
                {blkFrames.length ? (
                  blkFrames.map((f, i) => (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img key={i} src={f.url} alt="" draggable={false} className="h-full flex-1 object-cover" style={{ minWidth: 0 }} />
                  ))
                ) : (
                  <span className="h-full w-full bg-[#8b7cff]" />
                )}
              </span>
              {/* start · duration chip */}
              {width > 5 && (
                <span className="absolute left-1 top-1 z-10 rounded bg-black/60 px-1 py-px font-mono text-[9px] leading-snug text-white">
                  {mmss(b.start / 1000)} · {((b.end - b.start) / 1000).toFixed(0)}s
                </span>
              )}
              {/* real audio peaks along the bottom */}
              {blkPeaks.length > 0 && (
                <span className="absolute inset-x-0 bottom-0 flex h-5 items-end gap-[1px] bg-gradient-to-t from-black/70 to-transparent px-0.5">
                  {blkPeaks.map((p, i) => (
                    <span key={i} className="flex-1 rounded-t-sm bg-white/80" style={{ height: `${Math.max(8, p * 100)}%`, minWidth: 1 }} />
                  ))}
                </span>
              )}
              {active && <span className="absolute inset-0 bg-[#6d5dfb]/25" />}
            </div>
          );
        })}
        {/* draggable playhead */}
        <span
          style={{ left: `${Math.min(100, (cur * 1000 * 100) / totalMs)}%` }}
          className="pointer-events-none absolute top-0 h-full w-0.5 -translate-x-1/2 bg-[#111827]"
        >
          <span className="absolute -top-0.5 left-1/2 h-3 w-3 -translate-x-1/2 rounded-full border-2 border-white bg-[#6d5dfb] shadow" />
        </span>
      </div>
      <p className="mt-1 text-[11px] text-[#9aa1b2]">
        Click or drag the timeline to jump to any time. Split at the playhead to cut the video, then click a block to
        select it and Delete to remove it.
      </p>
    </ModalShell>
  );
}

/* ------------------------------------------------------------------ */
/* Crop: draggable box with corner handles directly on the video       */
/* ------------------------------------------------------------------ */
const Dot = () => (
  <span className="block h-3 w-3 -translate-x-0 rounded-full border-2 border-white bg-[#374151] shadow" />
);

const DEFAULT_CROP: CropRegion = { enabled: true, x: 0.12, y: 0.12, w: 0.76, h: 0.76, start_ms: 0, end_ms: 0 };

export function CropModal({
  source,
  crops,
  onCancel,
  onSave,
}: {
  source: string;
  crops: CropRegion[];
  onCancel: () => void;
  onSave: (crops: CropRegion[]) => void;
}) {
  // one crop per "angle": each region can carry its own time window, so parts
  // of the recording where the content sits somewhere else get their own box
  const [list, setList] = useState<CropRegion[]>(() =>
    crops.length ? crops.map((c) => ({ ...c })) : [{ ...DEFAULT_CROP }],
  );
  const [sel, setSel] = useState(0);
  const box = list[Math.min(sel, list.length - 1)];
  const patchAt = (idx: number, patch: Partial<CropRegion>) =>
    setList((l) => l.map((c, i) => (i === idx ? { ...c, ...patch } : c)));
  const patchSel = (patch: Partial<CropRegion>) => patchAt(sel, patch);
  const wrapRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [frame, setFrame] = useState({ w: 0, h: 0 });
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const [playing, setPlaying] = useState(false);
  // optional time window — the selected crop applies only within [rStart, rEnd]
  const rStart = box.start_ms ?? 0;
  const rEnd = box.end_ms ?? 0;
  const rangeOn = rEnd > rStart;

  // range timeline — the crop windows sit on a filmstrip as draggable blocks
  // (same interaction as the trim tool: drag the body to move, the side handles
  // to adjust, and anywhere else to scrub)
  const frames = useFilmstrip(source, 32);
  const stripRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<null | { mode: "seek" | "move" | "l" | "r"; idx: number; grab: number }>(null);
  const totalMs = Math.max(dur * 1000, 1);
  const msAtX = (clientX: number) => {
    const r = stripRef.current?.getBoundingClientRect();
    if (!r) return 0;
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * totalMs;
  };
  const seekMs = (ms: number) => {
    if (videoRef.current) videoRef.current.currentTime = Math.max(0, Math.min(ms, totalMs)) / 1000;
  };
  function stripDown(e: React.PointerEvent) {
    dragRef.current = { mode: "seek", idx: -1, grab: 0 };
    e.currentTarget.setPointerCapture?.(e.pointerId);
    seekMs(msAtX(e.clientX));
  }
  function blockDown(e: React.PointerEvent, idx: number, mode: "move" | "l" | "r") {
    e.stopPropagation();
    setSel(idx);
    dragRef.current = { mode, idx, grab: msAtX(e.clientX) - (list[idx].start_ms ?? 0) };
    stripRef.current?.setPointerCapture?.(e.pointerId);
  }
  function stripMove(e: React.PointerEvent) {
    const d = dragRef.current;
    if (!d) return;
    const at = msAtX(e.clientX);
    if (d.mode === "seek") {
      seekMs(at);
      return;
    }
    const c = list[d.idx];
    if (!c) return;
    const s = c.start_ms ?? 0;
    const en = c.end_ms ?? 0;
    if (d.mode === "move") {
      const w = en - s;
      const ns = Math.max(0, Math.min(at - d.grab, totalMs - w));
      patchAt(d.idx, { start_ms: Math.round(ns), end_ms: Math.round(ns + w) });
    } else if (d.mode === "l") {
      patchAt(d.idx, { start_ms: Math.round(Math.max(0, Math.min(at, en - 500))) });
    } else {
      patchAt(d.idx, { end_ms: Math.round(Math.min(totalMs, Math.max(at, s + 500))) });
    }
  }
  function stripUp() {
    dragRef.current = null;
  }

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const update = () => setFrame({ w: el.clientWidth, h: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const clamp = (v: number) => Math.max(0, Math.min(1, v));
  const handles = {
    topLeft: <Dot />, topRight: <Dot />, bottomLeft: <Dot />, bottomRight: <Dot />,
    top: <Dot />, bottom: <Dot />, left: <Dot />, right: <Dot />,
  };

  const L = box.x * 100, T = box.y * 100, R = (box.x + box.w) * 100, B = (box.y + box.h) * 100;

  return (
    <ModalShell
      title="Crop"
      onClose={onCancel}
      footer={
        <>
          {crops.length > 0 && (
            <button
              onClick={() => onSave([])}
              className="btn btn-ghost btn-sm text-[var(--text-2)]"
            >
              Remove all crops
            </button>
          )}
          <div className="ml-auto flex items-center gap-2">
            <button onClick={onCancel} className="btn btn-secondary">
              Cancel
            </button>
            <button
              onClick={() => {
                // clamp each region inside the frame (x+w ≤ 1) — otherwise the
                // reframe math shows a different area than selected
                onSave(
                  list.map((c) => {
                    const w = Math.min(1, Math.max(0.05, c.w));
                    const h = Math.min(1, Math.max(0.05, c.h));
                    const s = Math.round(c.start_ms ?? 0);
                    const e = Math.round(c.end_ms ?? 0);
                    return {
                      enabled: true,
                      x: Math.min(Math.max(0, c.x), 1 - w),
                      y: Math.min(Math.max(0, c.y), 1 - h),
                      w,
                      h,
                      start_ms: e > s ? s : 0,
                      end_ms: e > s ? e : 0,
                    };
                  }),
                );
              }}
              className="btn btn-primary"
            >
              Save changes
            </button>
          </div>
        </>
      }
    >
      <div ref={wrapRef} className="relative overflow-hidden rounded-xl bg-black">
        <video
          ref={videoRef}
          src={mediaUrl(source)}
          className="w-full"
          onLoadedMetadata={(e) => resolveDuration(e.currentTarget, setDur)}
          onTimeUpdate={(e) => setCur(e.currentTarget.currentTime)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />
        {/* dim outside the crop */}
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute bg-black/55" style={{ left: 0, top: 0, width: "100%", height: `${T}%` }} />
          <div className="absolute bg-black/55" style={{ left: 0, top: `${B}%`, width: "100%", bottom: 0 }} />
          <div className="absolute bg-black/55" style={{ left: 0, top: `${T}%`, width: `${L}%`, height: `${B - T}%` }} />
          <div className="absolute bg-black/55" style={{ left: `${R}%`, top: `${T}%`, right: 0, height: `${B - T}%` }} />
        </div>
        {frame.w > 0 && (
          <Rnd
            bounds="parent"
            size={{ width: box.w * frame.w, height: box.h * frame.h }}
            position={{ x: box.x * frame.w, y: box.y * frame.h }}
            onDrag={(_e, d) => patchSel({ x: clamp(d.x / frame.w), y: clamp(d.y / frame.h) })}
            onResize={(_e, _dir, ref, _delta, pos) =>
              patchSel({
                w: clamp(ref.offsetWidth / frame.w),
                h: clamp(ref.offsetHeight / frame.h),
                x: clamp(pos.x / frame.w),
                y: clamp(pos.y / frame.h),
              })
            }
            resizeHandleComponent={handles}
            className="border border-white/90"
          />
        )}
      </div>

      {/* playback */}
      <div className="mt-3 flex items-center gap-3">
        <span className="font-mono text-xs text-[var(--text-2)]">
          {mmss(cur)} / {mmss(dur)}
        </span>
        <button
          onClick={() => {
            const v = videoRef.current;
            if (!v) return;
            if (v.paused) void v.play();
            else v.pause();
          }}
          className="flex h-8 w-8 items-center justify-center rounded-full bg-[#6d5dfb] text-xs text-[var(--text)]"
        >
          {playing ? "❚❚" : "▶"}
        </button>
        <input
          type="range"
          min={0}
          max={dur || 1}
          step={0.1}
          value={cur}
          onChange={(e) => {
            if (videoRef.current) videoRef.current.currentTime = Number(e.target.value);
          }}
          className="flex-1 accent-[#6d5dfb]"
        />
      </div>

      {/* crop list — one region per "angle"; each can carry its own time range */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {list.map((c, i) => {
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
                  setSel(i);
                  const v = videoRef.current;
                  if (v && ranged) v.currentTime = (c.start_ms ?? 0) / 1000; // jump to its footage
                }}
              >
                Crop {i + 1}
                <span className="ml-1 font-mono text-[10px] text-[var(--text-3)]">
                  {ranged ? `${mmss((c.start_ms ?? 0) / 1000)}–${mmss((c.end_ms ?? 0) / 1000)}` : "whole video"}
                </span>
              </button>
              {list.length > 1 && (
                <button
                  title="Remove this crop"
                  onClick={() => {
                    setList((l) => l.filter((_, j) => j !== i));
                    setSel((s) => Math.max(0, Math.min(s > i ? s - 1 : s, list.length - 2)));
                  }}
                  className="text-[var(--text-3)] hover:text-[var(--text)]"
                >
                  ×
                </button>
              )}
            </span>
          );
        })}
        <button
          onClick={() => {
            // new crop for the footage from the playhead onward — when windows
            // overlap, the first crop in the list wins at render time
            const start = Math.round(cur * 1000);
            const end = Math.max(Math.round((dur || cur + 10) * 1000), start + 500);
            setList((l) => [...l, { ...DEFAULT_CROP, start_ms: start, end_ms: end }]);
            setSel(list.length);
          }}
          className="btn btn-ghost btn-sm"
        >
          ＋ Add crop
        </button>
      </div>

      {/* optional time window — the selected crop only applies within it */}
      <div className="mt-3 rounded-xl border border-[var(--border)] p-3">
        <label className="flex cursor-pointer items-center justify-between">
          <span>
            <span className="text-sm font-medium">
              Crop {list.length > 1 ? `${sel + 1} ` : ""}only a time range
            </span>
            <span className="mt-0.5 block text-xs text-[var(--text-3)]">
              Outside it the video stays uncropped — add another crop to cover it.
            </span>
          </span>
          <input
            type="checkbox"
            checked={rangeOn}
            onChange={(e) =>
              patchSel(
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
          className="relative mt-3 h-14 touch-none select-none overflow-hidden rounded-lg bg-[#0e1116] ring-1 ring-inset ring-[var(--border)]"
        >
          <Filmstrip frames={frames} className="opacity-70" />
          {list.map((c, i) => {
            const s = c.start_ms ?? 0;
            const en = c.end_ms ?? 0;
            if (en <= s) return null; // whole-video crop — no window to draw
            const left = (s / totalMs) * 100;
            const width = Math.max(0.5, ((en - s) / totalMs) * 100);
            const active = i === sel;
            return (
              <div
                key={i}
                onPointerDown={(e) => blockDown(e, i, "move")}
                style={{ left: `${left}%`, width: `${width}%` }}
                title={`Crop ${i + 1} · ${mmss(s / 1000)}–${mmss(en / 1000)} — drag to move`}
                className={`absolute inset-y-0 cursor-grab rounded-md border bg-[#6d5dfb]/30 backdrop-brightness-110 ${
                  active ? "border-[#6d5dfb] ring-2 ring-inset ring-[#6d5dfb]" : "border-white/40"
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
            style={{ left: `${Math.min(100, (cur * 1000 * 100) / totalMs)}%` }}
            className="pointer-events-none absolute inset-y-0 w-px bg-white"
          />
        </div>
        <p className="mt-1.5 text-right font-mono text-[11px] text-[var(--text-3)]">
          {rangeOn
            ? `Crop ${list.length > 1 ? sel + 1 : ""} applies ${mmss(rStart / 1000)} – ${mmss(rEnd / 1000)}`
            : "applies to the whole video"}
        </p>
      </div>
    </ModalShell>
  );
}
