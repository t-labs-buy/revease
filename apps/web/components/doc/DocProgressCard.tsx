"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ProgressBar, humanDuration } from "@/components/ProgressBar";
import { Spinner } from "@/components/ui";

/** Live progress of document generation, as reported by the worker
 *  ("Writing the guide…", "Capturing snapshot 3 of 8…"). */
export function DocProgressCard({
  phase,
  projectId,
  progress,
  message,
}: {
  phase: "queued" | "running";
  projectId: string;
  progress?: number | null;
  message?: string | null;
}) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);
  const pct = typeof progress === "number" ? Math.round(progress * 100) : null;
  const line = phase === "queued" ? message || "Waiting for a worker…" : message || "Working…";
  return (
    <section className="card mx-auto max-w-2xl p-6 sm:p-8">
      <div className="flex items-center gap-3">
        <Spinner className="text-[var(--brand)]" />
        <div className="min-w-0 flex-1">
          <p className="text-[15px] font-semibold text-[var(--text)]">Generating your documentation</p>
          <p className="mt-0.5 truncate text-[13.5px] text-[var(--text-2)]" aria-live="polite">
            {line}
          </p>
        </div>
        {pct != null && phase === "running" && <span className="font-mono text-[14px] font-semibold">{pct}%</span>}
      </div>
      <ProgressBar value={phase === "queued" ? null : progress ?? null} className="mt-5" />
      <p className="mt-3 text-[12.5px] text-[var(--text-3)]">
        {humanDuration(elapsed)} elapsed · you can leave and come back; it keeps running and the header shows progress.
      </p>
      <Link href={`/projects/${projectId}`} className="btn btn-ghost btn-sm mt-3 -ml-2">
        ← Back to project
      </Link>
    </section>
  );
}
