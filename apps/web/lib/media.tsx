"use client";

// Client-side media analysis for the timeline: sample real frame thumbnails
// (filmstrip) and decode the audio into peak amplitudes (waveform). Both are
// computed once per source and cached, so blocks/tracks read from memory rather
// than re-fetching or re-decoding. Nothing here touches the backend — the media
// endpoint already serves the file with CORS + HTTP Range.

import { useEffect, useState } from "react";
import { mediaUrl } from "./api";

export type Frame = { t: number; url: string }; // t = source milliseconds

// MediaRecorder WebM often reports duration===Infinity until forced to scan to
// the end. Resolve the real duration, then park the playhead back at 0.
function realDuration(v: HTMLVideoElement): Promise<number> {
  return new Promise((resolve) => {
    const d = v.duration;
    if (Number.isFinite(d) && d > 0) return resolve(d);
    const onChange = () => {
      if (Number.isFinite(v.duration) && v.duration > 0) {
        v.removeEventListener("durationchange", onChange);
        v.currentTime = 0;
        resolve(v.duration);
      }
    };
    v.addEventListener("durationchange", onChange);
    v.currentTime = 1e7;
  });
}

function seekTo(v: HTMLVideoElement, t: number): Promise<void> {
  return new Promise((resolve) => {
    const done = () => {
      v.removeEventListener("seeked", done);
      resolve();
    };
    v.addEventListener("seeked", done);
    v.currentTime = Math.min(Math.max(0, t), v.duration || t);
  });
}

/* ----------------------------- filmstrip ----------------------------- */

const stripCache = new Map<string, Frame[]>();
const stripInflight = new Map<string, Promise<Frame[]>>();

export function buildFilmstrip(source: string, count = 16, thumbW = 160): Promise<Frame[]> {
  const key = `${source}@${count}`;
  const cached = stripCache.get(key);
  if (cached) return Promise.resolve(cached);
  const running = stripInflight.get(key);
  if (running) return running;

  const job = (async (): Promise<Frame[]> => {
    const v = document.createElement("video");
    v.crossOrigin = "anonymous";
    v.muted = true;
    v.preload = "auto";
    v.src = mediaUrl(source);
    await new Promise<void>((res, rej) => {
      v.onloadedmetadata = () => res();
      v.onerror = () => rej(new Error("filmstrip: video load failed"));
    });
    const dur = await realDuration(v); // seconds
    const ar = v.videoWidth && v.videoHeight ? v.videoHeight / v.videoWidth : 9 / 16;
    const cw = thumbW;
    const ch = Math.max(1, Math.round(thumbW * ar));
    const canvas = document.createElement("canvas");
    canvas.width = cw;
    canvas.height = ch;
    const ctx = canvas.getContext("2d");
    if (!ctx) return [];
    const out: Frame[] = [];
    for (let i = 0; i < count; i++) {
      const tSec = (dur * (i + 0.5)) / count;
      await seekTo(v, tSec);
      try {
        ctx.drawImage(v, 0, 0, cw, ch);
        out.push({ t: tSec * 1000, url: canvas.toDataURL("image/jpeg", 0.5) });
      } catch {
        // drawImage can throw if the frame isn't ready; skip this sample
      }
    }
    v.src = "";
    v.load();
    return out;
  })();

  stripInflight.set(key, job);
  return job
    .then((frames) => {
      stripCache.set(key, frames);
      return frames;
    })
    .finally(() => stripInflight.delete(key));
}

export function useFilmstrip(source: string | null, count = 16): Frame[] {
  const [frames, setFrames] = useState<Frame[]>([]);
  useEffect(() => {
    if (!source) {
      setFrames([]);
      return;
    }
    let alive = true;
    buildFilmstrip(source, count)
      .then((f) => alive && setFrames(f))
      .catch(() => alive && setFrames([]));
    return () => {
      alive = false;
    };
  }, [source, count]);
  return frames;
}

/* ----------------------------- waveform ------------------------------ */

const waveCache = new Map<string, number[]>();
const waveInflight = new Map<string, Promise<number[]>>();

// Deterministic pseudo-waveform used only when the browser can't decode the
// audio track (rare) — still keyed off the source so it stays stable per video.
function fallbackPeaks(source: string, buckets: number): number[] {
  let seed = 0;
  for (let i = 0; i < source.length; i++) seed = (seed * 31 + source.charCodeAt(i)) % 1e6;
  return Array.from({ length: buckets }, (_, i) => {
    const n = Math.abs(Math.sin(i * 0.35 + seed) * 0.6 + Math.sin(i * 0.11 + seed) * 0.4);
    return 0.12 + n * 0.75;
  });
}

export function buildWaveform(source: string, buckets = 400): Promise<number[]> {
  const key = `${source}@${buckets}`;
  const cached = waveCache.get(key);
  if (cached) return Promise.resolve(cached);
  const running = waveInflight.get(key);
  if (running) return running;

  const job = (async (): Promise<number[]> => {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!AC) return fallbackPeaks(source, buckets);
    const resp = await fetch(mediaUrl(source));
    const buf = await resp.arrayBuffer();
    const ctx = new AC();
    let audio: AudioBuffer;
    try {
      audio = await ctx.decodeAudioData(buf);
    } catch {
      void ctx.close();
      return fallbackPeaks(source, buckets);
    }
    const ch = audio.getChannelData(0);
    const block = Math.max(1, Math.floor(ch.length / buckets));
    const peaks: number[] = [];
    let max = 0;
    for (let i = 0; i < buckets; i++) {
      let peak = 0;
      const start = i * block;
      for (let j = 0; j < block; j++) {
        const a = Math.abs(ch[start + j] || 0);
        if (a > peak) peak = a;
      }
      peaks.push(peak);
      if (peak > max) max = peak;
    }
    void ctx.close();
    return max > 0 ? peaks.map((p) => p / max) : fallbackPeaks(source, buckets);
  })();

  waveInflight.set(key, job);
  return job
    .then((peaks) => {
      waveCache.set(key, peaks);
      return peaks;
    })
    .catch(() => {
      const fb = fallbackPeaks(source, buckets);
      waveCache.set(key, fb);
      return fb;
    })
    .finally(() => waveInflight.delete(key));
}

export function useWaveform(source: string | null, buckets = 400): number[] {
  const [peaks, setPeaks] = useState<number[]>([]);
  useEffect(() => {
    if (!source) {
      setPeaks([]);
      return;
    }
    let alive = true;
    buildWaveform(source, buckets)
      .then((p) => alive && setPeaks(p))
      .catch(() => alive && setPeaks([]));
    return () => {
      alive = false;
    };
  }, [source, buckets]);
  return peaks;
}

/* --------------------------- render helpers -------------------------- */

// A continuous strip of real frame thumbnails. Absolutely fills its container
// (meant to sit behind selectable/draggable blocks).
export function Filmstrip({ frames, className = "" }: { frames: Frame[]; className?: string }) {
  if (!frames.length) return null;
  return (
    <div className={`pointer-events-none absolute inset-0 flex overflow-hidden ${className}`}>
      {frames.map((f, i) => (
        // eslint-disable-next-line @next/next/no-img-element
        <img key={i} src={f.url} alt="" draggable={false} className="h-full flex-1 object-cover" style={{ minWidth: 0 }} />
      ))}
    </div>
  );
}

// Centered amplitude bars from decoded peaks. `min` keeps a faint baseline.
export function Waveform({
  peaks,
  color = "currentColor",
  min = 0.08,
  className = "",
}: {
  peaks: number[];
  color?: string;
  min?: number;
  className?: string;
}) {
  if (!peaks.length) return null;
  return (
    <div className={`flex h-full items-center gap-[1px] ${className}`}>
      {peaks.map((p, i) => (
        <span
          key={i}
          className="flex-1 rounded-full"
          style={{ height: `${Math.max(min, p) * 100}%`, minWidth: 1, background: color }}
        />
      ))}
    </div>
  );
}
