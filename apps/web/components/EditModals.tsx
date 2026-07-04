"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Rnd } from "react-rnd";
import { mediaUrl, type EditSegment, type EditSpec } from "@/lib/api";

const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

export function ModalShell({
  title,
  onClose,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl bg-[var(--card)] shadow-2xl"
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
  const [segs, setSegs] = useState<EditSegment[]>(() => segments.map((s) => ({ ...s })));
  const [sel, setSel] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [zoom, setZoom] = useState(1);

  const totalMs = useMemo(
    () => Math.max(dur * 1000, ...segs.map((s) => s.source_end_ms), 1),
    [dur, segs],
  );
  const keptMs = segs.reduce((a, s) => a + Math.max(0, s.source_end_ms - s.source_start_ms), 0);

  function togglePlay() {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) void v.play();
    else v.pause();
  }
  function seekTo(sec: number) {
    if (videoRef.current) videoRef.current.currentTime = Math.max(0, Math.min(sec, dur || sec));
  }

  // Split the block containing the playhead into two (words split proportionally).
  function splitAtPlayhead() {
    const at = cur * 1000;
    setSegs((arr) => {
      const idx = arr.findIndex((s) => at > s.source_start_ms + 150 && at < s.source_end_ms - 150);
      if (idx < 0) return arr;
      const seg = arr[idx];
      const frac = (at - seg.source_start_ms) / (seg.source_end_ms - seg.source_start_ms);
      const wi = Math.round(seg.words.length * frac);
      const a: EditSegment = {
        ...seg,
        source_end_ms: Math.round(at),
        words: seg.words.slice(0, wi),
        removed: seg.removed.filter((r) => r < wi),
      };
      const b: EditSegment = {
        ...seg,
        step_id: `split_${Date.now()}`,
        source_start_ms: Math.round(at),
        words: seg.words.slice(wi),
        removed: seg.removed.filter((r) => r >= wi).map((r) => r - wi),
      };
      const out = [...arr];
      out.splice(idx, 1, a, b);
      return out;
    });
  }

  function deleteSelected() {
    if (!sel) return;
    setSegs((arr) => arr.filter((s) => s.step_id !== sel));
    setSel(null);
  }

  const ticks = 9;

  return (
    <ModalShell
      title="Trim"
      onClose={onCancel}
      footer={
        <>
          <span className="text-sm text-[var(--text-2)]">Total duration: {mmss(keptMs / 1000)} min</span>
          <div className="ml-auto flex items-center gap-2">
            <button onClick={onCancel} className="btn btn-secondary">
              Cancel
            </button>
            <button onClick={() => onSave(segs)} className="btn btn-primary">
              Save changes
            </button>
          </div>
        </>
      }
    >
      {/* video */}
      <div className="overflow-hidden rounded-xl bg-black">
        <video
          ref={videoRef}
          src={mediaUrl(source)}
          className="mx-auto max-h-[46vh] w-auto"
          onLoadedMetadata={(e) => setDur(e.currentTarget.duration || 0)}
          onTimeUpdate={(e) => setCur(e.currentTarget.currentTime)}
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
          ✂ Split at {mmss(cur)}
        </button>
        <button
          onClick={deleteSelected}
          disabled={!sel}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm text-[var(--text)] hover:bg-[var(--hover)] disabled:opacity-40"
        >
          🗑 Delete Block
        </button>
        <div className="mx-auto flex items-center gap-2">
          <button
            onClick={togglePlay}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-[#6d5dfb] text-xs text-[var(--text)]"
          >
            {playing ? "❚❚" : "▶"}
          </button>
          <span className="font-mono text-xs text-[var(--text-2)]">
            {mmss(cur)} / {mmss(dur)}
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

      {/* block timeline */}
      <div className="mt-3 overflow-x-auto pb-2">
        <div style={{ width: `${zoom * 100}%`, minWidth: "100%" }}>
          {/* ruler */}
          <div className="relative h-5 text-[10px] text-[var(--text-3)]">
            {Array.from({ length: ticks + 1 }).map((_, i) => (
              <span key={i} style={{ left: `${(i / ticks) * 100}%` }} className="absolute -translate-x-1/2">
                {mmss(((totalMs / 1000) * i) / ticks)}
              </span>
            ))}
            {/* playhead marker */}
            <span
              style={{ left: `${Math.min(100, (cur * 1000 * 100) / totalMs)}%` }}
              className="absolute top-2.5 -translate-x-1/2 text-[#6d5dfb]"
            >
              ▼
            </span>
          </div>
          {/* blocks with waveform */}
          <div
            className="relative h-16 cursor-pointer rounded-lg"
            onClick={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              seekTo((((e.clientX - r.left) / r.width) * totalMs) / 1000);
            }}
          >
            {segs.map((s) => {
              const left = (s.source_start_ms / totalMs) * 100;
              const width = Math.max(0.8, ((s.source_end_ms - s.source_start_ms) / totalMs) * 100);
              const active = sel === s.step_id;
              const bars = Math.max(6, Math.round(width * 1.6));
              return (
                <button
                  key={s.step_id}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSel(active ? null : s.step_id);
                    seekTo(s.source_start_ms / 1000);
                  }}
                  style={{ left: `${left}%`, width: `${width}%` }}
                  title={s.words.slice(0, 8).join(" ")}
                  className={`absolute top-0 h-full overflow-hidden rounded-md border-r border-white/40 ${
                    active ? "bg-[#4f3fd8] ring-2 ring-[#6d5dfb]" : "bg-[var(--brand-2)]"
                  }`}
                >
                  <span className="flex h-full items-center gap-[3px] px-1.5">
                    {Array.from({ length: bars }).map((_, i) => (
                      <span
                        key={i}
                        className="w-[2px] flex-none rounded bg-white/70"
                        style={{ height: `${18 + Math.abs(Math.sin(i * 2.1 + width)) * 55}%` }}
                      />
                    ))}
                  </span>
                </button>
              );
            })}
            {/* playhead line */}
            <span
              style={{ left: `${Math.min(100, (cur * 1000 * 100) / totalMs)}%` }}
              className="pointer-events-none absolute top-0 h-full w-0.5 bg-[var(--text)]"
            />
          </div>
        </div>
      </div>
      <p className="mt-1 text-[11px] text-[var(--text-3)]">
        Click a block to select it, then Delete Block — or Split at the playhead to cut a block in two.
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

  const totalMs = Math.max(dur * 1000, outMs, 1);
  const effOut = outMs || totalMs;

  function posToMs(clientX: number) {
    const r = stripRef.current?.getBoundingClientRect();
    if (!r) return 0;
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * totalMs;
  }
  function onMove(e: React.PointerEvent) {
    if (!drag.current) return;
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
          onLoadedMetadata={(e) => setDur(e.currentTarget.duration || 0)}
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

      {/* waveform strip with drag handles */}
      <div
        ref={stripRef}
        onPointerMove={onMove}
        onPointerUp={() => (drag.current = null)}
        className="relative mt-3 h-16 select-none overflow-hidden rounded-lg bg-[var(--hover)]"
      >
        {/* waveform */}
        <span className="flex h-full items-center gap-[3px] px-1.5">
          {Array.from({ length: 140 }).map((_, i) => (
            <span
              key={i}
              className="w-[2px] flex-none rounded bg-[var(--brand-2)]/80"
              style={{ height: `${18 + Math.abs(Math.sin(i * 1.7)) * 55}%` }}
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
        Drag the purple handles to choose which part of the recording to keep.
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

  // seed one block spanning the whole video once its duration is known
  function onMeta(d: number) {
    setDur(d);
    if (!seeded.current && d > 0) {
      setBlocks([{ id: "b0", start: 0, end: Math.round(d * 1000) }]);
      seeded.current = true;
    }
  }

  const totalMs = Math.max(dur * 1000, 1);
  const keptMs = blocks.reduce((a, b) => a + (b.end - b.start), 0);

  function seek(sec: number) {
    if (videoRef.current) videoRef.current.currentTime = Math.max(0, Math.min(sec, dur || sec));
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
      <div className="overflow-hidden rounded-xl bg-black">
        <video
          ref={videoRef}
          src={mediaUrl(source)}
          className="mx-auto max-h-[44vh] w-auto"
          onLoadedMetadata={(e) => onMeta(e.currentTarget.duration || 0)}
          onTimeUpdate={(e) => setCur(e.currentTarget.currentTime)}
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

      {/* block timeline */}
      <div className="relative mt-3 h-16 overflow-hidden rounded-lg bg-[#f4f5fa]">
        {blocks.map((b) => {
          const left = (b.start / totalMs) * 100;
          const width = Math.max(0.8, ((b.end - b.start) / totalMs) * 100);
          const active = sel === b.id;
          const bars = Math.max(6, Math.round(width * 1.6));
          return (
            <button
              key={b.id}
              onClick={() => {
                setSel(active ? null : b.id);
                seek(b.start / 1000);
              }}
              style={{ left: `${left}%`, width: `${width}%` }}
              className={`absolute top-0 h-full overflow-hidden rounded-md border-r border-white/50 ${active ? "bg-[#4f3fd8] ring-2 ring-[#6d5dfb]" : "bg-[#8b7cff]"}`}
            >
              <span className="flex h-full items-center gap-[3px] px-1.5">
                {Array.from({ length: bars }).map((_, i) => (
                  <span key={i} className="w-[2px] flex-none rounded bg-white/70" style={{ height: `${18 + Math.abs(Math.sin(i * 2.1 + width)) * 55}%` }} />
                ))}
              </span>
            </button>
          );
        })}
        <span style={{ left: `${Math.min(100, (cur * 1000 * 100) / totalMs)}%` }} className="pointer-events-none absolute top-0 h-full w-0.5 bg-[#111827]" />
      </div>
      <p className="mt-1 text-[11px] text-[#9aa1b2]">
        Split at the playhead to cut the video, then select a block and Delete to remove it.
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

export function CropModal({
  source,
  crop,
  onCancel,
  onSave,
}: {
  source: string;
  crop: EditSpec["crop"];
  onCancel: () => void;
  onSave: (crop: NonNullable<EditSpec["crop"]>) => void;
}) {
  const init =
    crop?.enabled && crop.w > 0 && crop.h > 0
      ? crop
      : { enabled: true, x: 0.12, y: 0.12, w: 0.76, h: 0.76 };
  const [box, setBox] = useState({ x: init.x, y: init.y, w: init.w, h: init.h });
  const wrapRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [frame, setFrame] = useState({ w: 0, h: 0 });
  const [cur, setCur] = useState(0);
  const [dur, setDur] = useState(0);
  const [playing, setPlaying] = useState(false);

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
          {crop?.enabled && (
            <button
              onClick={() => onSave({ enabled: false, x: 0, y: 0, w: 1, h: 1 })}
              className="btn btn-ghost btn-sm text-[var(--text-2)]"
            >
              Remove crop
            </button>
          )}
          <div className="ml-auto flex items-center gap-2">
            <button onClick={onCancel} className="btn btn-secondary">
              Cancel
            </button>
            <button
              onClick={() => onSave({ enabled: true, x: clamp(box.x), y: clamp(box.y), w: clamp(box.w), h: clamp(box.h) })}
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
          onLoadedMetadata={(e) => setDur(e.currentTarget.duration || 0)}
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
            onDrag={(_e, d) => setBox((b) => ({ ...b, x: clamp(d.x / frame.w), y: clamp(d.y / frame.h) }))}
            onResize={(_e, _dir, ref, _delta, pos) =>
              setBox({
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
    </ModalShell>
  );
}
