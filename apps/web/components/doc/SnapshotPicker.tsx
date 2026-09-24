"use client";

/**
 * Pick a different moment of the recording for a step's snapshot. The paused
 * <video> element *is* the preview (no canvas round-trip); a thumbnail strip
 * over the step's window gives quick jumps; the server grabs and annotates the
 * real frame once "Use this frame" is pressed.
 */

import { useEffect, useRef, useState } from "react";
import { mediaUrl, type DocStepV2 } from "@/lib/api";
import { ModalShell, resolveDuration } from "@/components/EditModals";
import { mmss } from "@/components/doc/DocView";
import { useWindowFrames } from "@/lib/media";
import { Spinner } from "@/components/ui";

const PAD_S = 2;

export function SnapshotPicker({
  source,
  step,
  stepIndex,
  onCancel,
  onPick,
}: {
  source: string; // raw video storage key
  step: DocStepV2;
  stepIndex: number;
  onCancel: () => void;
  onPick: (tSeconds: number) => void;
}) {
  const t0 = step.source.t_start ?? null;
  const t1 = step.source.t_end ?? null;
  const hasWindow = t0 != null && t1 != null && t1 > t0;
  const [duration, setDuration] = useState<number | null>(null);
  const lo = hasWindow ? Math.max(0, t0! - PAD_S) : 0;
  const hi = hasWindow ? t1! + PAD_S : (duration ?? 0);
  const hiClamped = duration != null ? Math.min(hi, duration) : hi;

  const [t, setT] = useState<number>(step.snapshot?.t ?? t0 ?? 0);
  const videoRef = useRef<HTMLVideoElement>(null);
  const raf = useRef<number | null>(null);
  const frames = useWindowFrames(source, lo, hiClamped, 12);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  // throttle seeks to one per frame: slider drags fire dozens of events per second
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (raf.current) cancelAnimationFrame(raf.current);
    raf.current = requestAnimationFrame(() => {
      if (Number.isFinite(v.duration)) v.currentTime = Math.min(t, v.duration || t);
    });
  }, [t]);

  const clamp = (x: number) => Math.min(hiClamped || x, Math.max(lo, x));
  const nudge = (d: number) => setT((x) => Number(clamp(x + d).toFixed(2)));

  return (
    <ModalShell
      title={`Choose a frame for step ${stepIndex + 1}`}
      onClose={onCancel}
      maxWidth="max-w-3xl"
      footer={
        <>
          <span className="mr-auto text-[13px] text-[var(--text-2)]">
            Frame at <span className="font-mono text-[var(--text)]">{mmss(t)}</span>
          </span>
          <button type="button" onClick={onCancel} className="btn btn-secondary">
            Cancel
          </button>
          <button type="button" onClick={() => onPick(Number(t.toFixed(3)))} className="btn btn-primary">
            Use this frame
          </button>
        </>
      }
    >
      <div className="pb-2">
        <video
          ref={videoRef}
          src={mediaUrl(source)}
          muted
          playsInline
          preload="auto"
          onLoadedMetadata={(e) => {
            const v = e.currentTarget;
            resolveDuration(v, (d) => setDuration(d));
            v.currentTime = t;
          }}
          className="w-full rounded-xl bg-black"
        />

        <div className="mt-3 flex items-center gap-2">
          <button type="button" onClick={() => nudge(-0.5)} className="btn btn-secondary btn-sm">
            −0.5s
          </button>
          <button type="button" onClick={() => nudge(-0.1)} className="btn btn-secondary btn-sm">
            −0.1s
          </button>
          <input
            type="range"
            min={lo}
            max={hiClamped || lo + 1}
            step={0.05}
            value={t}
            onChange={(e) => setT(Number(e.target.value))}
            aria-label="Frame time"
            className="mx-1 flex-1 accent-[#1E8F8E]"
          />
          <button type="button" onClick={() => nudge(0.1)} className="btn btn-secondary btn-sm">
            +0.1s
          </button>
          <button type="button" onClick={() => nudge(0.5)} className="btn btn-secondary btn-sm">
            +0.5s
          </button>
        </div>

        <div className="mt-3">
          {frames.length === 0 ? (
            <div className="flex h-16 items-center justify-center gap-2 text-[13px] text-[var(--text-3)]">
              <Spinner /> Loading frames…
            </div>
          ) : (
            <div className="flex gap-1 overflow-x-auto pb-1">
              {frames.map((f) => {
                const sec = f.t / 1000;
                const active = Math.abs(sec - t) < (hiClamped - lo) / 24;
                return (
                  <button
                    key={f.t}
                    type="button"
                    onClick={() => setT(Number(sec.toFixed(2)))}
                    title={mmss(sec)}
                    className={`flex-none overflow-hidden rounded-md ring-2 transition ${active ? "ring-[var(--brand)]" : "ring-transparent hover:ring-[var(--border-strong)]"}`}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={f.url} alt="" className="h-12 w-auto" />
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {step.snapshot?.key && (
          <div className="mt-3 flex items-center gap-3 text-[12.5px] text-[var(--text-3)]">
            <span>Current:</span>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={mediaUrl(step.snapshot.key)} alt="Current snapshot" className="h-12 rounded-md border border-[var(--border)]" />
            <span>{mmss(step.snapshot.t)}</span>
          </div>
        )}
        {hasWindow && (
          <p className="mt-2 text-[12px] text-[var(--text-3)]">
            This step was recorded between {mmss(t0)} and {mmss(t1)}; the slider covers a little either side.
          </p>
        )}
      </div>
    </ModalShell>
  );
}
