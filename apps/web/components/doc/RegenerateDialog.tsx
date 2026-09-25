"use client";

import { useEffect, useState } from "react";
import { ModalShell } from "@/components/EditModals";
import { GenerateOptions, useDocSkills } from "@/components/doc/DocGenerateCard";
import type { GenerateOpts } from "@/components/doc/useDocumentState";
import { Badge } from "@/components/ui";

export function RegenerateDialog({
  initial,
  onCancel,
  onConfirm,
}: {
  initial: GenerateOpts;
  onCancel: () => void;
  onConfirm: (opts: GenerateOpts) => void;
}) {
  const skills = useDocSkills();
  const [opts, setOpts] = useState<GenerateOpts>(initial);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <ModalShell
      title="Regenerate documentation"
      onClose={onCancel}
      maxWidth="max-w-lg"
      footer={
        <>
          <button type="button" onClick={onCancel} className="btn btn-secondary">
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onConfirm({ instruction: opts.instruction?.trim() || undefined, skill_id: opts.skill_id })}
            className="btn btn-primary"
          >
            Regenerate
          </button>
        </>
      }
    >
      <div className="pb-2">
        <GenerateOptions value={opts} onChange={setOpts} skills={skills} />
        <div className="mt-4 flex items-start gap-2 text-[13px] text-[var(--text-2)]">
          <Badge tone="amber">Heads up</Badge>
          <span>Regenerating rewrites the whole document. Your edits and custom snapshots will be replaced.</span>
        </div>
      </div>
    </ModalShell>
  );
}
