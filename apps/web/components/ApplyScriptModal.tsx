"use client";

import { useEffect, useRef, useState } from "react";
import { getSessionDetail, getSessionStatus, setSessionScript, spokenSeconds, spokenText } from "@/lib/api";

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
import { ModalShell } from "@/components/EditModals";
import { ScriptInput } from "@/components/ScriptInput";
import { Spinner } from "@/components/ui";

/** Editor: replace a recording's narration with a written script — or, in
 * `remove` mode, take the uploaded script away again. Either way the pipeline
 * re-runs and rebuilds every scene (the scenes were cut for that script), so
 * this is a whole-project action with a warning, not a per-line edit. It waits
 * for the new graph version to be ready and then hands back to the editor to
 * reload. */
export function ApplyScriptModal({
  sessionId,
  onClose,
  onApplied,
  mode = "apply",
}: {
  sessionId: string;
  onClose: () => void;
  onApplied: () => void;
  mode?: "apply" | "remove";
}) {
  const remove = mode === "remove";
  const [script, setScript] = useState("");
  const [recordingS, setRecordingS] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [phase, setPhase] = useState<"edit" | "waiting">("edit");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const baseVersion = useRef<number>(0);

  useEffect(() => {
    getSessionDetail(sessionId)
      .then((d) => {
        setScript(d.script ?? "");
        setRecordingS((d.duration_ms ?? 0) / 1000);
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, [sessionId]);

  // Poll until the run started by our PUT finishes: the status is "ready"
  // again AND the version moved past the one we saw before applying — a
  // status read right after the PUT can still show the previous run.
  useEffect(() => {
    if (phase !== "waiting") return;
    let stop = false;
    const tick = async () => {
      try {
        const s = await getSessionStatus(sessionId);
        if (stop) return;
        setMessage(s.message ?? null);
        const newer = (s.latest_version ?? 0) > baseVersion.current;
        if (newer && s.status === "ready") {
          onApplied();
          return;
        }
        if (newer && s.status === "error") {
          setError("Processing failed — the previous scenes are unchanged.");
          setPhase("edit");
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

  async function apply() {
    setError(null);
    try {
      const before = await getSessionStatus(sessionId);
      baseVersion.current = before.latest_version ?? 0;
      await setSessionScript(sessionId, remove ? "" : script);
      setPhase("waiting");
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    }
  }

  const waiting = phase === "waiting";
  return (
    <ModalShell
      title={remove ? "Remove the script" : "Apply a script"}
      onClose={waiting ? () => {} : onClose}
      maxWidth="max-w-2xl"
      footer={
        <>
          {error && <span className="text-sm text-red-500">{error}</span>}
          <span className="flex-1" />
          <button onClick={onClose} disabled={waiting} className="btn btn-ghost">
            Cancel
          </button>
          <button
            onClick={apply}
            disabled={waiting || !loaded || (!remove && !script.trim())}
            className={remove ? "btn btn-danger" : "btn btn-primary"}
          >
            {waiting ? (
              <>
                <Spinner /> {message || "Re-analysing the recording…"}
              </>
            ) : remove ? (
              "Remove & rebuild scenes"
            ) : (
              "Apply & rebuild scenes"
            )}
          </button>
        </>
      }
    >
      {remove ? (
        <p className="mb-3 text-sm text-[var(--text-2)]">
          The uploaded script is removed and the recording is analysed again without it: the scenes
          are rebuilt from the recording itself (its screen changes, or its own voice if it has one)
          and open empty, ready for Generate or a new script. <strong>Current scenes, narration
          edits and zoom tweaks are replaced.</strong> Project-level settings (voice, captions, media,
          crops) are kept.
        </p>
      ) : (
        <>
          <p className="mb-3 text-sm text-[var(--text-2)]">
            The recording is analysed again with this script as its narration: each sentence becomes
            a scene placed where the screen matches it. <strong>Current scenes, narration edits and
            zoom tweaks are replaced.</strong> Project-level settings (voice, captions, media, crops)
            are kept.
          </p>
          <ScriptInput value={script} onChange={setScript} rows={12} disabled={waiting || !loaded} />
          {(() => {
            // Warn before the pipeline runs: a script that needs more voice
            // time than there is footage freezes the picture for the rest.
            const voiceS = spokenSeconds(script);
            if (!recordingS || voiceS < 1) return null;
            const over = voiceS > recordingS * 1.05;
            return (
              <p className={`mt-2 text-xs ${over ? "text-red-600" : "text-[var(--text-3)]"}`}>
                ≈ {spokenText(script).split(/\s+/).filter(Boolean).length} words · about {mmss(voiceS)} of
                voice; the recording is {mmss(recordingS)}.
                {over && (
                  <>
                    {" "}
                    <strong>The script is longer than the video</strong> — the picture will freeze
                    while the voice finishes. Trim it to roughly {mmss(recordingS)} of speech (~
                    {Math.floor(recordingS * 2.3)} words) before applying.
                  </>
                )}
              </p>
            );
          })()}
        </>
      )}
      <div className="h-4" />
    </ModalShell>
  );
}
