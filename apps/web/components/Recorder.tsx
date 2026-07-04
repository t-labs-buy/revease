"use client";

import { useCallback, useRef, useState } from "react";
import {
  completeSession,
  createSession,
  postEvents,
  registerAndUpload,
  type CaptureEvent,
} from "@/lib/api";

type Phase = "idle" | "countdown" | "recording" | "paused" | "uploading" | "error";

/** Build a stable-ish CSS selector for an element (id > data-testid > tag:nth-of-type chain). */
function selectorFor(el: Element | null): string | null {
  if (!el) return null;
  if (el.id) return `#${el.id}`;
  const testid = el.getAttribute("data-testid");
  if (testid) return `[data-testid="${testid}"]`;
  const parts: string[] = [];
  let node: Element | null = el;
  let depth = 0;
  while (node && node.nodeType === 1 && depth < 4) {
    let part = node.tagName.toLowerCase();
    const parent = node.parentElement;
    if (parent) {
      const sibs = Array.from(parent.children).filter((c) => c.tagName === node!.tagName);
      if (sibs.length > 1) part += `:nth-of-type(${sibs.indexOf(node) + 1})`;
    }
    parts.unshift(part);
    node = node.parentElement;
    depth++;
  }
  return parts.join(" > ");
}

function labelFor(el: Element | null): string | null {
  if (!el) return null;
  const aria = el.getAttribute("aria-label");
  if (aria) return aria.slice(0, 120);
  const text = (el.textContent ?? "").trim().replace(/\s+/g, " ");
  return text ? text.slice(0, 120) : null;
}

export function Recorder({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [count, setCount] = useState(3);
  const [elapsed, setElapsed] = useState(0);
  const [micOn, setMicOn] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const eventsRef = useRef<CaptureEvent[]>([]);
  const seqRef = useRef(0);
  const startTsRef = useRef(0);
  const pausedMsRef = useRef(0);
  const pauseStartRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const now = () => performance.now() - startTsRef.current - pausedMsRef.current;

  const onClick = useCallback((e: MouseEvent) => {
    const el = e.target as Element | null;
    eventsRef.current.push({
      seq: seqRef.current++,
      type: "click",
      t_ms: Math.max(0, Math.round(now())),
      selector: selectorFor(el),
      text: labelFor(el),
      bbox: [e.clientX, e.clientY, 0, 0],
    });
  }, []);

  const onInput = useCallback((e: Event) => {
    const el = e.target as HTMLInputElement | null;
    if (!el) return;
    // Never capture password values (master §5 PII rule).
    const isPassword = el.tagName === "INPUT" && (el as HTMLInputElement).type === "password";
    eventsRef.current.push({
      seq: seqRef.current++,
      type: "input",
      t_ms: Math.max(0, Math.round(now())),
      selector: selectorFor(el),
      value_redacted: isPassword ? "[redacted]" : (el.value ?? "").slice(0, 200),
    });
  }, []);

  function attachListeners() {
    window.addEventListener("click", onClick, true);
    window.addEventListener("input", onInput, true);
  }
  function detachListeners() {
    window.removeEventListener("click", onClick, true);
    window.removeEventListener("input", onInput, true);
  }

  function startTimer() {
    timerRef.current = setInterval(() => setElapsed(Math.round(now() / 1000)), 250);
  }
  function stopTimer() {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
  }

  async function beginCapture() {
    setError(null);
    try {
      const display = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: true, // system audio where the browser allows it
      });
      let mic: MediaStream | null = null;
      if (micOn) {
        try {
          mic = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        } catch {
          /* mic denied */
        }
      }
      // Mix tab audio + mic into ONE track (MediaRecorder only encodes the first).
      const tabAudio = display.getAudioTracks();
      let audioTracks: MediaStreamTrack[] = [];
      if (tabAudio.length || mic) {
        const ac = new AudioContext();
        const dest = ac.createMediaStreamDestination();
        if (tabAudio.length) ac.createMediaStreamSource(new MediaStream(tabAudio)).connect(dest);
        if (mic) ac.createMediaStreamSource(mic).connect(dest);
        audioTracks = dest.stream.getAudioTracks();
      }
      const combined = new MediaStream([display.getVideoTracks()[0], ...audioTracks]);
      streamRef.current = combined;
      chunksRef.current = [];
      eventsRef.current = [];
      seqRef.current = 0;
      pausedMsRef.current = 0;

      // include an audio codec (opus) or the recording is video-only
      const mime =
        ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"].find((m) =>
          MediaRecorder.isTypeSupported(m),
        ) || "video/webm";
      const rec = new MediaRecorder(combined, { mimeType: mime });
      rec.ondataavailable = (ev) => ev.data.size > 0 && chunksRef.current.push(ev.data);
      // If the user stops sharing via the browser chrome, finalize.
      display.getVideoTracks()[0].addEventListener("ended", () => {
        if (recorderRef.current && recorderRef.current.state !== "inactive") stop();
      });
      recorderRef.current = rec;
      startTsRef.current = performance.now();
      rec.start(1000);
      attachListeners();
      startTimer();
      setElapsed(0);
      setPhase("recording");
    } catch (e) {
      setError(String(e));
      setPhase("error");
    }
  }

  function runCountdown() {
    setPhase("countdown");
    setCount(3);
    let c = 3;
    const iv = setInterval(() => {
      c -= 1;
      setCount(c);
      if (c <= 0) {
        clearInterval(iv);
        void beginCapture();
      }
    }, 1000);
  }

  function pause() {
    if (recorderRef.current?.state === "recording") {
      recorderRef.current.pause();
      pauseStartRef.current = performance.now();
      stopTimer();
      setPhase("paused");
    }
  }
  function resume() {
    if (recorderRef.current?.state === "paused") {
      pausedMsRef.current += performance.now() - pauseStartRef.current;
      recorderRef.current.resume();
      startTimer();
      setPhase("recording");
    }
  }

  async function stop() {
    const rec = recorderRef.current;
    if (!rec) return;
    stopTimer();
    detachListeners();
    const durationMs = Math.max(0, Math.round(now()));
    const done = new Promise<Blob>((resolve) => {
      rec.onstop = () => resolve(new Blob(chunksRef.current, { type: "video/webm" }));
    });
    rec.stop();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    const blob = await done;

    setPhase("uploading");
    try {
      const vp = { w: window.screen.width, h: window.screen.height };
      const session = await createSession(projectId, "recorder", vp);
      await registerAndUpload(session.id, "raw_video", "webm", blob);
      await postEvents(session.id, eventsRef.current);
      await completeSession(session.id, durationMs);
      recorderRef.current = null;
      setPhase("idle");
      onDone();
    } catch (e) {
      setError(String(e));
      setPhase("error");
    }
  }

  const mmss = (s: number) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

  return (
    <div>
      {(phase === "recording" || phase === "paused") && (
        <div className="mb-3 flex items-center gap-2 font-mono text-sm text-red-400">
          <span className="h-2 w-2 animate-pulse rounded-full bg-red-500" /> {mmss(elapsed)}
        </div>
      )}

      {phase === "idle" && (
        <div className="flex items-center gap-3">
          <button onClick={runCountdown} className="btn btn-primary">
            Start recording
          </button>
          <label className="flex items-center gap-2 text-sm text-zinc-400">
            <input type="checkbox" checked={micOn} onChange={(e) => setMicOn(e.target.checked)} />
            Mic
          </label>
        </div>
      )}

      {phase === "countdown" && (
        <div className="text-4xl font-bold tabular-nums text-violet-300">
          {count > 0 ? count : "Go"}
        </div>
      )}

      {(phase === "recording" || phase === "paused") && (
        <div className="flex flex-wrap items-center gap-2">
          {phase === "recording" ? (
            <button onClick={pause} className="btn btn-secondary btn-sm">
              Pause
            </button>
          ) : (
            <button onClick={resume} className="btn btn-secondary btn-sm">
              Resume
            </button>
          )}
          <button onClick={() => void stop()} className="btn btn-primary btn-sm">
            Stop &amp; save
          </button>
          <span className="text-xs text-zinc-500">{eventsRef.current.length} events</span>
        </div>
      )}

      {phase === "uploading" && <p className="text-sm text-zinc-400">Uploading…</p>}
      {phase === "error" && (
        <p className="mt-3 rounded-lg border border-red-900/60 bg-red-950/30 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}
      <p className="mt-3 text-xs text-zinc-600">
        Click log covers this tab only — the MV3 extension captures full click telemetry anywhere.
      </p>
    </div>
  );
}
