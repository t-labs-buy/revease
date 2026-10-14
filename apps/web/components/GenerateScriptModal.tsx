"use client";

import { useEffect, useRef, useState } from "react";
import { ModalShell } from "@/components/EditModals";
import { Spinner } from "@/components/ui";
import { generateScriptFromRecording, getSessionStatus, type ScriptMode } from "@/lib/api";

/** Asked before every Generate: what the video is about, in the author's own
 * words. Frames tell the model what happens on screen, not why it matters or
 * who it is for — without that the lines come out generic, so the brief is
 * mandatory. Remembered per project so a retry is one click.
 *
 * Generate always works from the whole recording: its frames (one a second)
 * go to the model, which writes as many lines as the footage has moments and
 * says where each starts; the recording is then re-analysed with that script,
 * so the scenes are rebuilt around the model's cuts — a background job this
 * modal waits on. The per-scene Generate (`onGenerate`) is only the fallback
 * for a project whose capture is unknown.
 *
 * Two lengths. "Fit to footage" caps each line at what its footage can carry
 * (the render freezes the last frame while a voice runs over); "Free length"
 * writes the full voiceover and leaves pacing to the editor's fit tools. */
export function GenerateScriptModal({
  projectId,
  sessionId,
  instruction,
  onClose,
  onGenerate,
  onApplied,
}: {
  projectId: string;
  sessionId: string | null;
  instruction?: string;
  onClose: () => void;
  /** No capture known: the caller runs the per-scene Generate instead. */
  onGenerate: (brief: string, mode: ScriptMode) => void;
  /** The scenes were rebuilt on the server; reload. */
  onApplied: () => void;
}) {
  const briefKey = `gen.brief.${projectId}`;
  const modeKey = `gen.mode.${projectId}`;
  const [brief, setBrief] = useState("");
  const [mode, setMode] = useState<ScriptMode>("fit");
  const [phase, setPhase] = useState<"edit" | "waiting">("edit");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const baseVersion = useRef<number>(0);

  useEffect(() => {
    try {
      setBrief(localStorage.getItem(briefKey) ?? "");
      const m = localStorage.getItem(modeKey);
      if (m === "fit" || m === "free") setMode(m);
    } catch {
      /* private mode: start empty */
    }
  }, [briefKey, modeKey]);

  // Whole-recording path: poll until the script job has run AND the
  // re-analysis it triggers has produced a newer graph version — the status
  // right after the POST still shows the previous run.
  useEffect(() => {
    if (phase !== "waiting" || !sessionId) return;
    let stop = false;
    const tick = async () => {
      try {
        const s = await getSessionStatus(sessionId);
        if (stop) return;
        const newer = (s.latest_version ?? 0) > baseVersion.current;
        const job = s.jobs.find((j) => j.stage === "script");
        if (!newer && job) {
          if (job.status === "error") {
            setError(job.message || "The AI could not write a script for this recording.");
            setPhase("edit");
            return;
          }
          setMessage(job.message ?? null);
          return;
        }
        if (newer) {
          setMessage(s.message ?? "Rebuilding the scenes…");
          if (s.status === "ready") onApplied();
          else if (s.status === "error") {
            setError("Processing failed — the previous scenes are unchanged.");
            setPhase("edit");
          }
        }
      } catch {
        /* transient; next tick retries */
      }
    };
    void tick();
    const iv = setInterval(() => void tick(), 2500);
    return () => {
      stop = true;
      clearInterval(iv);
    };
  }, [phase, sessionId, onApplied]);

  const ready = brief.trim().length >= 10;
  const waiting = phase === "waiting";

  async function submit() {
    if (!ready || waiting) return;
    try {
      localStorage.setItem(briefKey, brief.trim());
      localStorage.setItem(modeKey, mode);
    } catch {
      /* fine without */
    }
    if (!sessionId) {
      onGenerate(brief.trim(), mode);
      return;
    }
    setError(null);
    try {
      const before = await getSessionStatus(sessionId);
      baseVersion.current = before.latest_version ?? 0;
      await generateScriptFromRecording(sessionId, brief.trim(), mode, instruction);
      setMessage("Queued…");
      setPhase("waiting");
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    }
  }

  const choice = (
    checked: boolean,
    onPick: () => void,
    label: string,
    hint: string,
  ) => (
    <label
      className={`flex cursor-pointer gap-2 rounded-lg border px-3 py-2 text-sm ${
        checked ? "border-[var(--accent)] bg-[var(--hover)]" : "border-[var(--border)]"
      } ${waiting ? "opacity-60" : ""}`}
    >
      <input type="radio" checked={checked} onChange={onPick} disabled={waiting} className="mt-0.5" />
      <span>
        <span className="font-medium">{label}</span>
        <span className="block text-xs text-[var(--text-3)]">{hint}</span>
      </span>
    </label>
  );

  return (
    <ModalShell
      title="What is this video about?"
      onClose={waiting ? () => {} : onClose}
      maxWidth="max-w-xl"
      footer={
        <>
          <span className="flex-1 text-xs text-[var(--text-3)]">
            {error ? (
              <span className="text-red-500">{error}</span>
            ) : ready ? (
              ""
            ) : (
              "A sentence or two is required."
            )}
          </span>
          <button onClick={onClose} disabled={waiting} className="btn btn-ghost">
            Cancel
          </button>
          <button onClick={submit} disabled={!ready || waiting} className="btn btn-primary">
            {waiting ? (
              <>
                <Spinner /> {message || "Working…"}
              </>
            ) : (
              "✨ Generate"
            )}
          </button>
        </>
      }
    >
      <p className="mb-3 text-sm text-[var(--text-2)]">
        Tell the AI what it is narrating: the product or feature, who the viewer is, and anything
        the script must say or avoid. This goes to the model with every scene.
      </p>
      <textarea
        autoFocus
        value={brief}
        onChange={(e) => setBrief(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit();
        }}
        rows={4}
        maxLength={2000}
        disabled={waiting}
        placeholder="e.g. A demo of creating an A2A integration test suite in iVolve TestEase, for SAP integration consultants evaluating the tool. Mention that the environment list comes from connected tenants."
        className="input w-full resize-y text-left text-sm leading-relaxed"
      />
      {sessionId && (
        <p className="mt-3 text-xs text-[var(--text-3)]">
          The AI watches the whole recording frame by frame and decides the scenes itself.
          Current scenes, narration edits and zoom tweaks are replaced.
        </p>
      )}
      <div className="mt-4">
        <div className="mb-1 text-xs font-medium text-[var(--text-2)]">Length</div>
        <div className="grid gap-2 sm:grid-cols-2">
          {choice(
            mode === "fit",
            () => setMode("fit"),
            "Fit to footage",
            "Each line is kept short enough for the footage it covers, so the picture never waits for the voice.",
          )}
          {choice(
            mode === "free",
            () => setMode("free"),
            "Free length",
            "No word limit. The full voiceover a presenter would record; use Fit narration afterwards if it runs long.",
          )}
        </div>
      </div>
      <div className="h-2" />
    </ModalShell>
  );
}
