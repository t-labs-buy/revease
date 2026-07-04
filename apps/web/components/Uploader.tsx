"use client";

import { useRef, useState } from "react";
import { completeSession, createSession, registerAndUpload } from "@/lib/api";

const ACCEPT = ["video/mp4", "video/webm"];

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
      const session = await createSession(projectId, "upload");
      await registerAndUpload(session.id, "raw_video", ext, file);
      // No telemetry on a plain upload -> complete() flags telemetry=absent (P2 CV territory).
      await completeSession(session.id);
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
      className={`rounded-xl border border-dashed p-6 text-center transition-colors ${
        drag ? "border-violet-500 bg-violet-500/5" : "border-zinc-700 bg-zinc-950/30"
      }`}
    >
      <p className="text-sm text-zinc-400">
        {busy ? "Uploading…" : "Drag & drop an mp4 / webm"}
      </p>
      {!busy && (
        <button onClick={() => inputRef.current?.click()} className="btn btn-secondary btn-sm mt-3">
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
      {error && <p className="mt-3 text-sm text-red-300">{error}</p>}
    </div>
  );
}
