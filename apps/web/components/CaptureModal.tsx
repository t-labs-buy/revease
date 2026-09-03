"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  completeSession,
  createProject,
  createSession,
  postEvents,
  registerAndUpload,
  type CaptureEvent,
} from "@/lib/api";
import { IconDoc, IconPlus, IconUpload, IconVideo } from "@/components/icons";
import { Spinner } from "@/components/ui";
import { readDurationMs } from "@/components/Uploader";

export type CaptureIntent = "record" | "upload" | "video" | "doc";

const MAX_BYTES = 2 * 1024 * 1024 * 1024; // 2 GB
const MIN_BYTES = 50 * 1024; // 50 KB
const ACCEPT = "video/mp4,video/quicktime,.mp4,.mov";

const fmtSize = (b: number) =>
  b >= 1024 * 1024 * 1024
    ? `${(b / 1024 / 1024 / 1024).toFixed(2)} GB`
    : `${(b / 1024 / 1024).toFixed(1)} MB`;

const stamp = () =>
  new Date().toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

// Turn an uploaded file name into a readable project title (drop extension,
// swap separators for spaces, Title Case). The AI renames it after analysis.
const prettyName = (filename: string): string => {
  const base = filename
    .replace(/\.[^./\\]+$/, "")
    .replace(/[-_.]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const titled = base.replace(/\b\w/g, (c) => c.toUpperCase());
  return titled || `Upload · ${stamp()}`;
};

function selectorFor(el: Element | null): string | null {
  if (!el || el.nodeType !== 1) return null;
  if ((el as HTMLElement).id) return `#${(el as HTMLElement).id}`;
  return el.tagName.toLowerCase();
}

export function CaptureModal({
  intent,
  onClose,
}: {
  intent: CaptureIntent;
  onClose: () => void;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<"choose" | "record" | "upload">(
    intent === "record" ? "record" : intent === "upload" ? "upload" : "choose",
  );
  const [error, setError] = useState<string | null>(null);

  // carry the intent so the session page auto-opens the editor/doc when ready
  // land on the pre-generate review page (trim/crop/voice + pick outputs & video skill)
  const goToSession = (pid: string, sid: string) =>
    router.push(`/projects/${pid}/prepare?sid=${sid}${intent === "doc" ? "&intent=doc" : ""}`);

  // ---- recording ----
  const [recPhase, setRecPhase] = useState<"idle" | "recording" | "saving" | "saveError">("idle");
  const [elapsed, setElapsed] = useState(0);
  const [hasAudio, setHasAudio] = useState<boolean | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const eventsRef = useRef<CaptureEvent[]>([]);
  const idsRef = useRef<{ pid: string; sid: string } | null>(null);
  const startTsRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const seqRef = useRef(0);
  const stoppingRef = useRef(false);
  const savedRef = useRef<{ blob: Blob; durationMs: number } | null>(null);
  const displayRef = useRef<MediaStream | null>(null);
  const micRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);

  const onClick = useCallback((e: MouseEvent) => {
    eventsRef.current.push({
      seq: seqRef.current++,
      type: "click",
      t_ms: Math.max(0, Math.round(performance.now() - startTsRef.current)),
      selector: selectorFor(e.target as Element),
      bbox: [e.clientX, e.clientY, 0, 0],
    });
  }, []);

  async function startRecording() {
    setError(null);
    try {
      // must be first in the user gesture
      const display = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
      displayRef.current = display;
      let mic: MediaStream | null = null;
      try {
        mic = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      } catch {
        /* mic optional */
      }
      micRef.current = mic;

      // Mix tab audio + mic into ONE track — MediaRecorder only encodes the first
      // audio track, so appending mic after tab audio would silently drop the voice.
      const tabAudio = display.getAudioTracks();
      let audioTracks: MediaStreamTrack[] = [];
      if (tabAudio.length || mic) {
        const ac = new AudioContext();
        audioCtxRef.current = ac;
        const dest = ac.createMediaStreamDestination();
        if (tabAudio.length) ac.createMediaStreamSource(new MediaStream(tabAudio)).connect(dest);
        if (mic) ac.createMediaStreamSource(mic).connect(dest);
        audioTracks = dest.stream.getAudioTracks();
      }
      const stream = new MediaStream([display.getVideoTracks()[0], ...audioTracks]);
      // audio is required for the transcript + AI voiceover
      setHasAudio(audioTracks.length > 0);
      const project = await createProject(`Screen Recording · ${stamp()}`);
      const session = await createSession(project.id, "recorder", {
        w: window.screen.width,
        h: window.screen.height,
      });
      idsRef.current = { pid: project.id, sid: session.id };

      streamRef.current = stream;
      chunksRef.current = [];
      eventsRef.current = [];
      seqRef.current = 0;
      // include an audio codec (opus) or the recording is video-only
      const mime =
        ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"].find((m) =>
          MediaRecorder.isTypeSupported(m),
        ) || "video/webm";
      const rec = new MediaRecorder(stream, { mimeType: mime });
      rec.ondataavailable = (ev) => ev.data.size > 0 && chunksRef.current.push(ev.data);
      display.getVideoTracks()[0].addEventListener("ended", () => void stopRecording());
      recRef.current = rec;
      startTsRef.current = performance.now();
      rec.start(1000);
      // Note: we do NOT log page clicks here — they'd be clicks on the Refract UI,
      // not the recorded surface. The script comes from the spoken transcript.
      setElapsed(0);
      timerRef.current = setInterval(
        () => setElapsed(Math.round((performance.now() - startTsRef.current) / 1000)),
        250,
      );
      setRecPhase("recording");
    } catch (e) {
      setError(String(e));
    }
  }

  async function finalize(blob: Blob, durationMs: number) {
    const ids = idsRef.current;
    if (!ids) throw new Error("no session");
    if (!blob.size) throw new Error("No video was captured — please try again.");
    await registerAndUpload(ids.sid, "raw_video", "webm", blob);
    await postEvents(ids.sid, eventsRef.current);
    await completeSession(ids.sid, durationMs);
    goToSession(ids.pid, ids.sid);
  }

  // Called by the modal Stop button AND the browser's native "Stop sharing".
  async function stopRecording() {
    if (stoppingRef.current) return;
    stoppingRef.current = true;
    const rec = recRef.current;
    if (!rec || !idsRef.current) {
      stoppingRef.current = false;
      return;
    }
    if (timerRef.current) clearInterval(timerRef.current);
    const durationMs = Math.max(0, Math.round(performance.now() - startTsRef.current));
    const done = new Promise<Blob>((resolve) => {
      rec.onstop = () => resolve(new Blob(chunksRef.current, { type: "video/webm" }));
    });
    try {
      rec.stop();
    } catch {
      /* already inactive */
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    displayRef.current?.getTracks().forEach((t) => t.stop());
    micRef.current?.getTracks().forEach((t) => t.stop());
    audioCtxRef.current?.close().catch(() => {});
    const blob = await done;
    savedRef.current = { blob, durationMs };
    setRecPhase("saving");
    try {
      await finalize(blob, durationMs);
    } catch (e) {
      console.error("capture save failed:", e);
      setError(String(e));
      setRecPhase("saveError"); // keep the recording so the user can retry
    }
  }

  async function retrySave() {
    if (!savedRef.current) return;
    setError(null);
    setRecPhase("saving");
    try {
      await finalize(savedRef.current.blob, savedRef.current.durationMs);
    } catch (e) {
      setError(String(e));
      setRecPhase("saveError");
    }
  }

  // ---- upload ----
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

  function pickFile(f: File) {
    setError(null);
    const okType = /\.(mp4|mov)$/i.test(f.name) || ["video/mp4", "video/quicktime"].includes(f.type);
    if (!okType) return setError("Please choose an MP4 or MOV file.");
    if (f.size > MAX_BYTES) return setError(`File is ${fmtSize(f.size)} — the limit is 2 GB.`);
    if (f.size < MIN_BYTES) return setError("File looks too small / empty.");
    setFile(f);
  }

  async function confirmUpload() {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const ext = /\.mov$/i.test(file.name) ? "mov" : "mp4";
      const durationMs = await readDurationMs(file);
      const project = await createProject(prettyName(file.name));
      const session = await createSession(project.id, "upload");
      await registerAndUpload(session.id, "raw_video", ext, file);
      await completeSession(session.id, durationMs);
      goToSession(project.id, session.id);
    } catch (e) {
      setError(String(e));
      setUploading(false);
    }
  }

  const title =
    intent === "doc" ? "Create a Document" : intent === "video" ? "Create a Video" : "New capture";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={recPhase === "recording" || recPhase === "saving" ? undefined : onClose}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-3xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-2xl shadow-black/30"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 flex-none items-center justify-center rounded-2xl bg-gradient-to-br from-[#6d5dfb] to-[#a855f7] text-white shadow-sm shadow-[#6d5dfb]/30">
            {intent === "doc" ? <IconDoc width={18} height={18} /> : <IconVideo width={18} height={18} />}
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="text-lg font-semibold tracking-tight text-[var(--text)]">{title}</h2>
            <p className="text-xs text-[var(--text-3)]">Record your screen or upload a file.</p>
          </div>
          {recPhase !== "recording" && recPhase !== "saving" && (
            <button
              onClick={onClose}
              className="flex h-8 w-8 flex-none items-center justify-center rounded-lg text-[var(--text-3)] hover:bg-[var(--hover)] hover:text-[var(--text)]"
            >
              ✕
            </button>
          )}
        </div>

        {error && (
          <p className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
            {error}
          </p>
        )}

        {/* choose */}
        {mode === "choose" && (
          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            <button
              onClick={() => setMode("record")}
              className="group flex flex-col items-center gap-3 rounded-2xl border border-[var(--border)] bg-[var(--input-bg)] py-8 transition-all hover:border-[#6d5dfb]/60 hover:bg-[#6d5dfb]/5"
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-[#6d5dfb] to-[#8b5cf6] text-white shadow-sm shadow-[#6d5dfb]/30 transition-transform group-hover:scale-105">
                <IconVideo width={22} height={22} />
              </span>
              <span className="text-sm font-semibold text-[var(--text)]">Record your screen</span>
              <span className="text-xs text-[var(--text-3)]">Pick a tab, window, or screen</span>
            </button>
            <button
              onClick={() => setMode("upload")}
              className="group flex flex-col items-center gap-3 rounded-2xl border border-[var(--border)] bg-[var(--input-bg)] py-8 transition-all hover:border-[#6d5dfb]/60 hover:bg-[#6d5dfb]/5"
            >
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-[#8b5cf6] to-[#ec4899] text-white shadow-sm shadow-[#8b5cf6]/30 transition-transform group-hover:scale-105">
                <IconUpload width={22} height={22} />
              </span>
              <span className="text-sm font-semibold text-[var(--text)]">Upload a video</span>
              <span className="text-xs text-[var(--text-3)]">MP4 or MOV</span>
            </button>
          </div>
        )}

        {/* record */}
        {mode === "record" && (
          <div className="mt-5">
            {recPhase === "idle" && (
              <div className="text-center">
                <p className="text-sm text-[var(--text-2)]">
                  You&apos;ll be asked which tab, window, or screen to record. Click, navigate, and
                  narrate — then stop.
                </p>
                <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-left text-xs text-amber-600 dark:text-amber-300">
                  🔊 <strong>Enable audio</strong> so we can transcribe and voice your video: tick
                  <strong> “Share tab audio”</strong> in the picker, and allow your microphone when
                  prompted.
                </div>
                <button onClick={startRecording} className="btn btn-primary mt-4">
                  <IconPlus width={16} height={16} /> Start recording
                </button>
                <p className="mt-3 text-xs text-[var(--text-3)]">
                  For full click telemetry across any site, use the MV3 extension.
                </p>
                {intent === "video" || intent === "doc" ? (
                  <button onClick={() => setMode("choose")} className="btn btn-ghost btn-sm mt-2">
                    ← back
                  </button>
                ) : null}
              </div>
            )}
            {recPhase === "recording" && (
              <div className="flex flex-col items-center gap-4 py-4">
                <div className="flex items-center gap-2 font-mono text-lg text-red-400">
                  <span className="h-3 w-3 animate-pulse rounded-full bg-red-500" />
                  {String(Math.floor(elapsed / 60)).padStart(2, "0")}:
                  {String(elapsed % 60).padStart(2, "0")}
                </div>
                {hasAudio === false ? (
                  <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-center text-xs text-red-200">
                    ⚠ No audio is being captured — the transcript &amp; AI voiceover need audio.
                    Stop, then re-record with “Share tab audio” or your mic enabled.
                  </div>
                ) : (
                  <p className="flex items-center gap-1.5 text-xs text-emerald-400">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> audio OK
                  </p>
                )}
                <p className="text-xs text-[var(--text-3)]">
                  Recording… switch to the tab you&apos;re capturing, then come back and stop.
                </p>
                <button onClick={() => void stopRecording()} className="btn btn-primary">
                  Stop &amp; save
                </button>
              </div>
            )}
            {recPhase === "saving" && (
              <div className="flex items-center justify-center gap-2 py-8 text-sm text-[var(--text-2)]">
                <Spinner /> Saving & processing…
              </div>
            )}
            {recPhase === "saveError" && (
              <div className="py-6 text-center">
                <p className="text-sm text-[var(--text-2)]">
                  Recording captured, but saving failed. Your video isn&apos;t lost — retry the
                  upload.
                </p>
                <button onClick={retrySave} className="btn btn-primary mt-4">
                  Retry upload
                </button>
              </div>
            )}
          </div>
        )}

        {/* upload */}
        {mode === "upload" && (
          <div className="mt-5">
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                const f = e.dataTransfer.files[0];
                if (f) pickFile(f);
              }}
              className="flex flex-col items-center rounded-2xl border border-dashed border-[var(--border-strong)] bg-[var(--input-bg)] p-8 text-center"
            >
              <span className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-[#6d5dfb]/12 text-[var(--brand-2)]">
                {file ? "🎬" : <IconUpload width={24} height={24} />}
              </span>
              {file ? (
                <div>
                  <div className="text-sm font-medium text-[var(--text)]">{file.name}</div>
                  <div className="mt-1 text-xs text-[var(--text-3)]">{fmtSize(file.size)}</div>
                </div>
              ) : (
                <p className="text-sm text-[var(--text-2)]">Drag &amp; drop, or choose a file</p>
              )}
              <button
                onClick={() => inputRef.current?.click()}
                className="btn btn-secondary btn-sm mt-3"
              >
                {file ? "Choose another" : "Choose file"}
              </button>
              <input
                ref={inputRef}
                type="file"
                accept={ACCEPT}
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) pickFile(f);
                }}
              />
            </div>
            <p className="mt-2 text-center text-xs text-[var(--text-3)]">MP4 or MOV · up to 2 GB</p>
            <div className="mt-4 flex justify-end gap-2">
              {(intent === "video" || intent === "doc") && (
                <button onClick={() => setMode("choose")} className="btn btn-ghost btn-sm">
                  ← back
                </button>
              )}
              <button
                onClick={confirmUpload}
                disabled={!file || uploading}
                className="btn btn-primary"
              >
                {uploading ? (
                  <>
                    <Spinner /> Uploading…
                  </>
                ) : (
                  "Upload & process"
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
