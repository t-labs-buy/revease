"use client";

/**
 * The timeline's "Media" row. The overview timeline runs on the SOURCE clock,
 * so inserted clips (which pause the recording) are drawn as markers at the
 * scene boundary they follow, and custom-range overlays as blocks you can
 * drag to move or pull at the edges to resize. Whole-video overlays span the
 * row as a thin bar.
 */

import { useRef } from "react";
import { effectiveInserts, type EditSpec, type MediaOverlay } from "@/lib/api";

export function TlMediaTrack({
  spec,
  totalMs,
  curMs,
  seekTo,
  onRange,
  onSelect,
}: {
  spec: EditSpec;
  totalMs: number;
  curMs: number;
  seekTo: (s: number) => void;
  onRange: (id: string, start_ms: number, end_ms: number) => void;
  onSelect: (id: string) => void;
}) {
  const segs = spec.segments;
  const pct = (ms: number) => `${Math.max(0, Math.min(100, (ms / Math.max(1, totalMs)) * 100))}%`;
  const markerAt = (slot: number) =>
    slot < 0 ? 0 : slot >= segs.length ? totalMs : segs[slot]?.source_end_ms ?? totalMs;
  const inserts = effectiveInserts(spec);
  const overlays = spec.overlays ?? [];
  const whole = overlays.filter((o) => typeof o.range !== "object");
  return (
    <>
      {whole.length > 0 && (
        <div
          className="absolute inset-x-0 top-1 h-1.5 rounded-full bg-[#1E8F8E]/35"
          title={`${whole.length} overlay${whole.length > 1 ? "s" : ""} on the whole video`}
        />
      )}
      {overlays
        .filter((o) => typeof o.range === "object")
        .map((o) => (
          <RangeBlock
            key={o.id}
            ov={o}
            totalMs={totalMs}
            live={typeof o.range === "object" && curMs >= o.range.start_ms && curMs <= o.range.end_ms}
            onRange={(a, b) => onRange(o.id, a, b)}
            onSelect={() => onSelect(o.id)}
          />
        ))}
      {inserts.map((it, k) => (
        <button
          key={`${it.id}-${k}`}
          onClick={() => seekTo(markerAt(it.slot) / 1000)}
          style={{ left: pct(markerAt(it.slot)) }}
          className="absolute bottom-1 z-[1] h-3.5 w-3.5 -translate-x-1/2 rotate-45 rounded-[3px] border border-white bg-[#16283C] shadow"
          title={`${it.type === "title" ? `Title card “${it.title ?? ""}”` : it.name || it.type} — full screen, ${Math.round(
            (it.duration_ms || 0) / 100,
          ) / 10}s`}
        />
      ))}
    </>
  );
}

function RangeBlock({
  ov,
  totalMs,
  live,
  onRange,
  onSelect,
}: {
  ov: MediaOverlay;
  totalMs: number;
  live: boolean;
  onRange: (start_ms: number, end_ms: number) => void;
  onSelect: () => void;
}) {
  const r = ov.range as { start_ms: number; end_ms: number };
  const ref = useRef<HTMLDivElement>(null);

  function drag(e: React.PointerEvent, mode: "move" | "start" | "end") {
    e.stopPropagation();
    onSelect();
    const track = ref.current?.closest("[data-track]") as HTMLElement | null;
    if (!track) return;
    const pxPerMs = track.getBoundingClientRect().width / Math.max(1, totalMs);
    const x0 = e.clientX;
    const { start_ms: s0, end_ms: e0 } = r;
    const len = e0 - s0;
    const move = (ev: PointerEvent) => {
      const d = Math.round((ev.clientX - x0) / pxPerMs);
      if (mode === "move") {
        const s = Math.max(0, Math.min(totalMs - len, s0 + d));
        onRange(s, s + len);
      } else if (mode === "start") {
        onRange(Math.max(0, Math.min(e0 - 200, s0 + d)), e0);
      } else {
        onRange(s0, Math.min(totalMs, Math.max(s0 + 200, e0 + d)));
      }
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  return (
    <div
      ref={ref}
      onPointerDown={(e) => drag(e, "move")}
      style={{ left: `${(r.start_ms / totalMs) * 100}%`, width: `${Math.max(0.75, ((r.end_ms - r.start_ms) / totalMs) * 100)}%` }}
      className={`absolute top-1/2 flex h-6 -translate-y-1/2 cursor-grab touch-none items-center overflow-hidden rounded-md px-2 text-[10px] font-medium text-white ${live ? "bg-[#1E8F8E] ring-2 ring-[#16283C]/40" : "bg-[#1E8F8E]/70"}`}
      title={ov.name || "Overlay"}
    >
      <span onPointerDown={(e) => drag(e, "start")} className="absolute inset-y-0 left-0 w-1.5 cursor-ew-resize bg-white/40" />
      <span className="truncate">{ov.type === "video" ? "▶ " : ""}{ov.name || "Overlay"}</span>
      <span onPointerDown={(e) => drag(e, "end")} className="absolute inset-y-0 right-0 w-1.5 cursor-ew-resize bg-white/40" />
    </div>
  );
}
