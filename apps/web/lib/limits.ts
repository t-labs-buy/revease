/**
 * Video limits: 500 MB and 30 minutes per recording or upload.
 *
 * Why: one long capture ties up the media worker for its whole normalize +
 * transcribe, and step extraction / narration quality drops on very long
 * sessions. Shorter parts process faster and edit better. The server enforces
 * the same numbers (REFRACT_MAX_VIDEO_MB / REFRACT_MAX_VIDEO_MINUTES); these
 * checks just say so before a long upload starts instead of after.
 *
 * Recordings never fail on the limit: the recorders stop and save by
 * themselves a little before it (RECORD_STOP_*), leaving headroom for the
 * last chunk and the WebM container.
 */

export const MAX_VIDEO_MB = 500;
export const MAX_VIDEO_MIN = 30;
export const MAX_VIDEO_BYTES = MAX_VIDEO_MB * 1024 * 1024;
export const MAX_VIDEO_MS = MAX_VIDEO_MIN * 60 * 1000;

/** Recorders stop here — just under the limits. */
export const RECORD_STOP_BYTES = MAX_VIDEO_BYTES - 12 * 1024 * 1024;
export const RECORD_STOP_MS = MAX_VIDEO_MS - 2000;
/** …and warn from here. */
export const RECORD_WARN_BYTES = Math.round(MAX_VIDEO_BYTES * 0.85);
export const RECORD_WARN_MS = MAX_VIDEO_MS - 5 * 60 * 1000;

export const LIMIT_LABEL = `up to ${MAX_VIDEO_MB} MB and ${MAX_VIDEO_MIN} minutes`;

/**
 * Recording quality = the encoder bit rate MediaRecorder is given. Left unset,
 * Chrome encodes at ~2.5 Mbps whatever the size, which smears 1080p screen
 * text before the file ever reaches the server — the softness no export
 * setting can recover. Sharp text at 1080p wants ~8 Mbps, but the 500 MB cap
 * then holds only ~8 minutes, so the user picks: sharp and short, or long.
 * "long" is sized so the full MAX_VIDEO_MIN fits under the size cap.
 */
export type RecordQuality = "sharp" | "long";
export const RECORD_QUALITIES: Record<RecordQuality, { bps: number; label: string; blurb: string }> = {
  sharp: { bps: 8_000_000, label: "Sharp", blurb: "crisp text, best for demos" },
  long: {
    bps: Math.floor((RECORD_STOP_BYTES * 8) / (RECORD_STOP_MS / 1000) / 100_000) * 100_000,
    label: "Long",
    blurb: "softer picture, full length",
  },
};
export const DEFAULT_RECORD_QUALITY: RecordQuality = "sharp";
export const RECORD_AUDIO_BPS = 96_000; // opus; speech needs no more

/** Minutes a recording at `bps` lasts before the size cap stops it, or the
 * time cap if that comes first. */
export function recordMinutesAt(bps: number): number {
  const bySize = (RECORD_STOP_BYTES * 8) / bps / 60;
  return Math.floor(Math.min(bySize, RECORD_STOP_MS / 60000));
}

/** getDisplayMedia constraints: the screen's real pixel size and 30 fps as
 * ideals (Chrome otherwise captures HiDPI screens scaled down and at whatever
 * frame rate it likes). Ideals never fail a capture; Chrome picks the best it can. */
export function captureConstraints(): MediaStreamConstraints {
  const dpr = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;
  const w = typeof screen !== "undefined" ? screen.width * dpr : 1920;
  const h = typeof screen !== "undefined" ? screen.height * dpr : 1080;
  return {
    video: { frameRate: { ideal: 30 }, width: { ideal: Math.round(w) }, height: { ideal: Math.round(h) } },
    audio: true,
  };
}

const SPLIT_HINT = `Please split it into parts of at most ${MAX_VIDEO_MIN} minutes / ${MAX_VIDEO_MB} MB and upload each part separately.`;

const mb = (b: number) => (b >= 1024 ** 3 ? `${(b / 1024 ** 3).toFixed(2)} GB` : `${Math.round(b / 1024 / 1024)} MB`);
const mins = (ms: number) => `${Math.floor(ms / 60000)} min ${Math.round((ms % 60000) / 1000)} s`;

/** Size check (instant). Null when fine, else the message to show. */
export function videoSizeError(size: number): string | null {
  return size > MAX_VIDEO_BYTES ? `This video is ${mb(size)} — the limit is ${MAX_VIDEO_MB} MB. ${SPLIT_HINT}` : null;
}

/** Size + duration check for a picked video file. Also returns the duration
 * it read, so callers don't probe the file twice. */
export async function checkVideoFile(file: File): Promise<{ error: string | null; durationMs?: number }> {
  const sizeErr = videoSizeError(file.size);
  if (sizeErr) return { error: sizeErr };
  const durationMs = await readDurationMs(file);
  if (durationMs && durationMs > MAX_VIDEO_MS + 1000) {
    return { error: `This video is ${mins(durationMs)} long — the limit is ${MAX_VIDEO_MIN} minutes. ${SPLIT_HINT}`, durationMs };
  }
  return { error: null, durationMs };
}

/** Why a running recording must stop now, or null to keep going. */
export function recordingLimitHit(bytes: number, elapsedMs: number): "size" | "time" | null {
  if (bytes >= RECORD_STOP_BYTES) return "size";
  if (elapsedMs >= RECORD_STOP_MS) return "time";
  return null;
}

export const recordingStoppedNote = (why: "size" | "time") =>
  why === "time"
    ? `Recording reached the ${MAX_VIDEO_MIN}-minute limit, so it stopped and was saved. To continue, start a new recording for the next part.`
    : `Recording reached the ${MAX_VIDEO_MB} MB limit, so it stopped and was saved. To continue, start a new recording for the next part.`;

/** "12:03 / 30:00" style clock for the recording timer. */
export const clockOf = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

/** Read a video file's real length before uploading. The recorder knows how long
 *  it ran, but an upload has no such context — without this the capture is stored
 *  with duration 0 and shows no length anywhere in the UI. Never rejects: on
 *  unreadable metadata it resolves undefined and the upload proceeds without a
 *  duration. (Used by every video upload path.) */
export function readDurationMs(file: File): Promise<number | undefined> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const probe = document.createElement("video");
    const done = (ms?: number) => {
      URL.revokeObjectURL(url);
      resolve(ms);
    };
    probe.preload = "metadata";
    probe.onloadedmetadata = () =>
      done(Number.isFinite(probe.duration) ? Math.round(probe.duration * 1000) : undefined);
    probe.onerror = () => done(undefined); // unreadable metadata — upload anyway
    probe.src = url;
  });
}
