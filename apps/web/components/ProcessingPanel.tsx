"use client";

/**
 * Live view of a recording being understood: one overall bar, what is happening
 * now ("Converting video · 12:03 of 28:46"), elapsed and estimated time left,
 * and a row per stage. Shown on the prepare page from the moment a recording
 * lands — not only after "Generate" — because the heavy work (conversion and
 * transcription) starts immediately and can take a long time on long recordings.
 */

import type { JobStatus, SessionStatus } from "@/lib/api";
import { ProgressBar, humanDuration } from "@/components/ProgressBar";
import { IconCheck, IconX } from "@/components/icons";
import { Spinner } from "@/components/ui";

export const PIPELINE_STAGES = [
  { key: "media", label: "Converting video", hint: "Makes the recording seekable and extracts audio and keyframes" },
  { key: "whisper", label: "Transcribing narration", hint: "Turns your speech into a timed transcript" },
  { key: "merge", label: "Detecting steps", hint: "Splits the recording at each action" },
  { key: "extract", label: "Labelling steps with AI", hint: "Names each step and writes the script" },
];

/** "Converting video · 04:17 of 10:00" under a "Converting video" row reads
 *  twice — keep just the detail when the message repeats the label. */
function detailOf(message: string | null | undefined, label: string): string | null {
  if (!message) return null;
  if (message.toLowerCase().startsWith(label.toLowerCase())) {
    const rest = message.slice(label.length).replace(/^\s*[·:…-]+\s*/, "").trim();
    return rest || null;
  }
  return message;
}

function StageRow({ label, hint, job, done }: { label: string; hint: string; job?: JobStatus; done: boolean }) {
  const st = done ? "done" : job?.status ?? "pending";
  const icon =
    st === "done" ? (
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--brand)] text-white">
        <IconCheck width={12} height={12} />
      </span>
    ) : st === "running" ? (
      <Spinner className="h-5 w-5 text-[var(--brand)]" />
    ) : st === "error" ? (
      <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--warning)] text-white" title="Skipped after an error">
        <IconX width={12} height={12} />
      </span>
    ) : (
      <span className="block h-5 w-5 rounded-full border-2 border-[var(--border-strong)]" />
    );
  return (
    <li className="flex items-start gap-3">
      <span className="mt-0.5 flex-none">{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className={`text-[13.5px] font-medium ${st === "pending" ? "text-[var(--text-3)]" : "text-[var(--text)]"}`}>{label}</span>
          {st === "running" && typeof job?.progress === "number" && (
            <span className="font-mono text-[12px] text-[var(--text-2)]">{Math.round(job.progress * 100)}%</span>
          )}
        </div>
        {st === "running" ? (
          <>
            <p className="mt-0.5 truncate text-[12px] text-[var(--text-2)]">{detailOf(job?.message, label) || hint}</p>
            <ProgressBar value={job?.progress ?? null} className="mt-1.5" />
          </>
        ) : st === "error" ? (
          <p className="mt-0.5 text-[12px] text-[var(--text-3)]">{job?.message || "Skipped — continuing without it"}</p>
        ) : null}
      </div>
    </li>
  );
}

export function ProcessingPanel({ status, ready }: { status: SessionStatus | null; ready: boolean }) {
  const jobFor = (k: string) => status?.jobs.find((j) => j.stage === k);
  const overall = ready ? 1 : status?.progress ?? null;
  const waiting = !ready && (!status || status.jobs.length === 0);
  const stalled = !ready && !!status?.stalled;

  return (
    <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="flex items-baseline justify-between gap-3">
        <span className="eyebrow">{ready ? "Processing complete" : "Processing your recording"}</span>
        {overall != null && <span className="font-mono text-[13px] font-semibold text-[var(--text)]">{Math.round(overall * 100)}%</span>}
      </div>
      <ProgressBar value={waiting ? null : overall} className="mt-2" tone={stalled ? "warn" : "brand"} />
      {!ready && (
        <p className="mt-2 text-[12.5px] text-[var(--text-2)]">
          {waiting
            ? "Queued — waiting for a worker to pick this up…"
            : [
                status?.elapsed_s != null ? `${humanDuration(status.elapsed_s)} elapsed` : null,
                status?.eta_s != null ? `about ${humanDuration(status.eta_s)} left` : "estimating time left…",
              ]
                .filter(Boolean)
                .join(" · ")}
        </p>
      )}
      {stalled && (
        <p className="mt-2 rounded-md bg-[var(--warning)]/10 px-2.5 py-1.5 text-[12px] text-[#9a6a12]">
          No update for a few minutes. The server may be busy with another long recording; this will resume on its own.
        </p>
      )}
      <ol className="mt-4 space-y-3">
        {PIPELINE_STAGES.map((s) => (
          <StageRow key={s.key} label={s.label} hint={s.hint} job={jobFor(s.key)} done={ready} />
        ))}
      </ol>
      {!ready && (
        <p className="mt-4 border-t border-[var(--border)] pt-3 text-[12px] text-[var(--text-3)]">
          You can leave this page — processing continues, and the indicator in the header shows its progress.
        </p>
      )}
    </section>
  );
}
