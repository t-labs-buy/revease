"use client";

import { useEffect, useRef, useState } from "react";
import {
  getAutoEdit,
  mediaUrl,
  startAutoEdit,
  type AutoEditJob,
  type AutoEditOptions,
} from "@/lib/api";
import { Spinner } from "@/components/ui";

const LEVELS: AutoEditOptions["aggressiveness"][] = [
  "gentle",
  "balanced",
  "aggressive",
];

const secs = (ms?: number) => {
  const s = Math.max(0, Math.round((ms ?? 0) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

export function AutoEditCard({ projectId }: { projectId: string }) {
  const [job, setJob] = useState<AutoEditJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [level, setLevel] =
    useState<AutoEditOptions["aggressiveness"]>("balanced");
  const [captions, setCaptions] = useState(true);
  const [zoom, setZoom] = useState(true);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  async function run() {
    setError(null);
    try {
      const j = await startAutoEdit(projectId, {
        aggressiveness: level,
        captions,
        zoom,
      });
      setJob(j);
      pollRef.current = setInterval(async () => {
        const r = await getAutoEdit(j.id);
        setJob(r);
        if (r.status === "done" || r.status === "error") {
          if (pollRef.current) clearInterval(pollRef.current);
        }
      }, 2000);
    } catch (e) {
      setError(String(e));
    }
  }

  const running = job && job.status !== "done" && job.status !== "error";
  const st = job?.stats_json;

  return (
    <section className="card p-5">
      <div className="label mb-1">Auto-edit</div>
      <p className="text-sm text-zinc-400">
        Speed up silent stretches and zoom toward on-screen motion — straight
        from the recording, no clicks needed.
      </p>

      {!running && job?.status !== "done" && (
        <div className="mt-4 space-y-3">
          <div>
            <div className="mb-1.5 text-xs text-zinc-500">Pace</div>
            <div className="inline-flex rounded-lg border border-zinc-800 bg-zinc-900/40 p-0.5">
              {LEVELS.map((l) => (
                <button
                  key={l}
                  onClick={() => setLevel(l)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium capitalize transition-colors ${
                    level === l
                      ? "bg-zinc-800 text-[var(--text)]"
                      : "text-zinc-400 hover:text-zinc-100"
                  }`}
                >
                  {l}
                </button>
              ))}
            </div>
          </div>
          <div className="flex gap-4 text-sm text-zinc-300">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={captions}
                onChange={(e) => setCaptions(e.target.checked)}
                className="accent-violet-500"
              />
              Captions
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={zoom}
                onChange={(e) => setZoom(e.target.checked)}
                className="accent-violet-500"
              />
              Auto-zoom
            </label>
          </div>
          <button onClick={run} className="btn btn-secondary w-full">
            {job ? "Re-run" : "Auto-edit (speed + zoom)"}
          </button>
        </div>
      )}

      {running && (
        <div className="mt-4 flex items-center gap-2 text-sm text-zinc-400">
          <Spinner /> Analyzing & re-timing…
        </div>
      )}

      {job?.status === "done" && st && (
        <div className="mt-4">
          <div className="flex items-baseline gap-2">
            <span className="text-sm text-zinc-500 line-through">
              {secs(st.source_duration_ms)}
            </span>
            <span className="text-2xl font-semibold text-[var(--text)]">
              {secs(st.output_duration_ms)}
            </span>
          </div>
          <div className="mt-1 text-xs text-zinc-500">
            {st.sped_up} region{st.sped_up === 1 ? "" : "s"} sped up ·{" "}
            {st.zoomed} zoomed
          </div>
          {st.captions ? (
            <div className="mt-1 text-xs text-emerald-400">
              captions burned in
            </div>
          ) : null}
          {job.output_key && (
            <video
              src={mediaUrl(job.output_key)}
              controls
              className="mt-3 w-full rounded-lg bg-black"
            />
          )}
          <button
            onClick={() => setJob(null)}
            className="btn btn-ghost btn-sm mt-2 w-full"
          >
            New auto-edit
          </button>
        </div>
      )}

      {(job?.status === "error" || error) && (
        <p className="mt-3 text-xs text-red-300">
          {error ?? JSON.stringify(job?.error_json)}
        </p>
      )}
    </section>
  );
}
