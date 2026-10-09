"use client";

import { useEffect, useState } from "react";
import { ModalShell } from "@/components/EditModals";

/** Asked before every Generate: what the video is about, in the author's own
 * words. Scene labels and frames tell the model what happens on screen, not
 * why it matters or who it is for — without that the lines come out generic,
 * so the brief is mandatory. Remembered per project so a retry is one click. */
export function GenerateScriptModal({
  projectId,
  onClose,
  onGenerate,
}: {
  projectId: string;
  onClose: () => void;
  onGenerate: (brief: string) => void;
}) {
  const key = `gen.brief.${projectId}`;
  const [brief, setBrief] = useState("");

  useEffect(() => {
    try {
      setBrief(localStorage.getItem(key) ?? "");
    } catch {
      /* private mode: start empty */
    }
  }, [key]);

  const ready = brief.trim().length >= 10;

  function submit() {
    if (!ready) return;
    try {
      localStorage.setItem(key, brief.trim());
    } catch {
      /* fine without */
    }
    onGenerate(brief.trim());
  }

  return (
    <ModalShell
      title="What is this video about?"
      onClose={onClose}
      maxWidth="max-w-xl"
      footer={
        <>
          <span className="flex-1 text-xs text-[var(--text-3)]">
            {ready ? "" : "A sentence or two is required."}
          </span>
          <button onClick={onClose} className="btn btn-ghost">
            Cancel
          </button>
          <button onClick={submit} disabled={!ready} className="btn btn-primary">
            ✨ Generate
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
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
        }}
        rows={5}
        maxLength={2000}
        placeholder="e.g. A demo of creating an A2A integration test suite in iVolve TestEase, for SAP integration consultants evaluating the tool. Mention that the environment list comes from connected tenants."
        className="input w-full resize-y text-left text-sm leading-relaxed"
      />
      <div className="h-4" />
    </ModalShell>
  );
}
