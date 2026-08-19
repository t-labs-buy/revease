"use client";

import { useRef, useState } from "react";
import { completeSession, createSession, registerAndUpload } from "@/lib/api";

const ACCEPT = ["video/mp4", "video/webm"];

/** Read a video file's real length before uploading. The recorder knows how long
 *  it ran, but an upload has no such context — without this the capture is stored
 *  with duration 0 and shows no length anywhere in the UI. */
function readDurationMs(file: File): Promise<number | undefined> {
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

export function Uploader({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    setError(null);
    if (!ACCEPT.includes(file.type) && !/\.(mp4|webm)$/i.test(file.name)) {
      setError("Please choose an mp4 or webm video.");
      return;
    }
    setBusy(true);
    try {
      const ext = /\.webm$/i.test(file.name) ? "webm" : "mp4";
      const durationMs = await readDurationMs(file);
      const session = await createSession(projectId, "upload");
      await registerAndUpload(session.id, "raw_video", ext, file);
      // No telemetry on a plain upload -> complete() flags telemetry=absent (P2 CV territory).
      await completeSession(session.id, durationMs);
      onDone();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        const f = e.dataTransfer.files[0];
        if (f) void handleFile(f);
      }}
      className={`rounded-2xl border border-dashed px-6 py-8 text-center transition-colors ${
        drag
          ? "border-[#7C3AED] bg-[#7C3AED]/5"
          : "border-[var(--border-strong)] bg-[var(--hover)]"
      }`}
    >
      <p className="text-sm text-[var(--text-2)]">
        {busy ? "Uploading…" : "Drag & drop an mp4 / webm"}
      </p>
      {!busy && (
        <button
          onClick={() => inputRef.current?.click()}
          className="mt-3 inline-flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-2 text-sm font-semibold text-[var(--text)] shadow-[var(--shadow-card)] transition-colors hover:bg-[var(--hover)]"
        >
          Choose a video
        </button>
      )}
      <input
        ref={inputRef}
        type="file"
        accept="video/mp4,video/webm"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void handleFile(f);
        }}
      />
      {error && (
        <p className="mt-3 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </p>
      )}
    </div>
  );
}
