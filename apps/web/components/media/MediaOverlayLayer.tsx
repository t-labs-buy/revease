"use client";

/**
 * Media-tab overlays (logos, picture-in-picture) drawn over the preview.
 *
 * This layer covers the WHOLE output frame — backdrop padding included —
 * because the renderer composites overlays over the finished frame, not the
 * inset recording (unlike Elements, which live inside the video box). Boxes
 * are draggable/resizable while the Media tab is open; positions are stored
 * normalized (0..1) exactly as worker/pipeline/placement.overlay_box reads them.
 *
 * Visibility mirrors the render on the preview's source clock: "all"/"body"
 * always show (inserted clips aren't previewed), a custom range only inside
 * [start_ms, end_ms]. A picture-in-picture clip plays muted, kept within
 * ~0.3 s of where the render would be.
 */

import { useEffect, useRef, useState } from "react";
import { Rnd } from "react-rnd";
import { mediaUrl, type EditSpec, type MediaOverlay } from "@/lib/api";

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

export const overlayVisible = (ov: MediaOverlay, curMs: number) =>
  typeof ov.range === "object" ? curMs >= ov.range.start_ms && curMs <= ov.range.end_ms : true;

export function MediaOverlayLayer({
  spec,
  setSpec,
  editing,
  curMs,
  playing,
  selId,
  setSelId,
}: {
  spec: EditSpec;
  setSpec: (s: EditSpec) => void;
  editing: boolean;
  curMs: number;
  playing: boolean;
  selId: string | null;
  setSelId: (id: string | null) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  const all = spec.overlays ?? [];
  const shown = all.filter((ov) => overlayVisible(ov, curMs));
  const setOv = (id: string, p: Partial<MediaOverlay>) =>
    setSpec({ ...spec, overlays: all.map((o) => (o.id === id ? { ...o, ...p } : o)) });
  const { w, h } = size;

  return (
    <div ref={ref} className="pointer-events-none absolute inset-0 z-[5] overflow-hidden">
      {w > 0 &&
        shown.map((ov) => {
          const sel = editing && selId === ov.id;
          return (
            <Rnd
              key={ov.id}
              className={`${editing ? "pointer-events-auto cursor-move" : "pointer-events-none"} ${sel ? "outline outline-2 outline-[#1E8F8E]" : ""}`}
              bounds="parent"
              disableDragging={!editing}
              enableResizing={editing}
              lockAspectRatio
              size={{ width: ov.w * w, height: ov.h * h }}
              position={{ x: ov.x * w, y: ov.y * h }}
              onMouseDown={() => editing && setSelId(ov.id)}
              onDragStop={(_e, d) => setOv(ov.id, { x: clamp01(d.x / w), y: clamp01(d.y / h) })}
              onResizeStop={(_e, _dir, el, _delta, pos) =>
                setOv(ov.id, {
                  w: clamp01(el.offsetWidth / w),
                  h: clamp01(el.offsetHeight / h),
                  x: clamp01(pos.x / w),
                  y: clamp01(pos.y / h),
                })
              }
            >
              <div className="h-full w-full" style={{ opacity: ov.opacity ?? 1 }}>
                {ov.type === "video" ? (
                  <PipVideo ov={ov} curMs={curMs} playing={playing} />
                ) : (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={mediaUrl(ov.media_key)} alt="" className="h-full w-full object-contain" draggable={false} />
                )}
              </div>
            </Rnd>
          );
        })}
    </div>
  );
}

function PipVideo({ ov, curMs, playing }: { ov: MediaOverlay; curMs: number; playing: boolean }) {
  const ref = useRef<HTMLVideoElement>(null);
  const start = typeof ov.range === "object" ? ov.range.start_ms : 0;
  useEffect(() => {
    const v = ref.current;
    if (!v || !Number.isFinite(v.duration) || v.duration <= 0) return;
    let t = Math.max(0, (curMs - start) / 1000);
    if (ov.loop !== false) t %= v.duration;
    else t = Math.min(t, v.duration);
    if (Math.abs(v.currentTime - t) > 0.3) v.currentTime = t;
  }, [curMs, start, ov.loop]);
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    if (playing) void v.play().catch(() => {});
    else v.pause();
  }, [playing]);
  return (
    <video
      ref={ref}
      src={mediaUrl(ov.media_key)}
      muted
      playsInline
      loop={ov.loop !== false}
      preload="auto"
      className="h-full w-full rounded-md object-contain"
    />
  );
}

/** Background music in the preview: plays the chosen track (not the built-in
 * pad, which exists only at render time) at its gain, following play/pause and
 * seeks on the preview clock. Ducking/fades are render-only. */
/** Fired by the Media tab's volume slider: the preview plays the track for a
 * moment even while the video is paused, so you hear the level you're setting. */
export const MUSIC_AUDITION_EVENT = "refract:music-audition";
const AUDITION_MS = 1500;

export function MusicPreview({ spec, curMs, playing }: { spec: EditSpec; curMs: number; playing: boolean }) {
  const ref = useRef<HTMLAudioElement>(null);
  const m = spec.music;
  const src = m?.enabled && m.storage_key ? mediaUrl(m.storage_key) : null;
  const [audition, setAudition] = useState(false);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const on = () => {
      setAudition(true);
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => setAudition(false), AUDITION_MS);
    };
    window.addEventListener(MUSIC_AUDITION_EVENT, on);
    return () => {
      window.removeEventListener(MUSIC_AUDITION_EVENT, on);
      if (timer) clearTimeout(timer);
    };
  }, []);
  useEffect(() => {
    const a = ref.current;
    if (!a) return;
    a.volume = Math.max(0, Math.min(1, 10 ** ((m?.gain_db ?? -18) / 20) * 2.5));
  }, [m?.gain_db, src]);
  useEffect(() => {
    const a = ref.current;
    if (!a || !src || !Number.isFinite(a.duration) || a.duration <= 0) return;
    const t = ((m?.start_ms ?? 0) / 1000 + curMs / 1000) % a.duration;
    if (Math.abs(a.currentTime - t) > 0.5) a.currentTime = t;
  }, [curMs, src, m?.start_ms]);
  useEffect(() => {
    const a = ref.current;
    if (!a || !src) return;
    if (playing || audition) void a.play().catch(() => {});
    else a.pause();
  }, [playing, audition, src]);
  if (!src) return null;
  return <audio ref={ref} src={src} loop preload="auto" />;
}
