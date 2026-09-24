"use client";

/** Controlled editor over a DocV2. Every mutation produces a new object and goes
 *  through `onChange`, so the page owns autosave. Reordering is positional
 *  (move up/down); step ids never change. */

import { useState } from "react";
import type { DocStepV2, DocV2 } from "@/lib/api";
import { AutosizeTextarea } from "@/components/doc/AutosizeTextarea";
import { ListEditor } from "@/components/doc/ListEditor";
import { StepCard } from "@/components/doc/StepCard";
import { Inline } from "@/components/doc/DocView";
import { IconLightbulb, IconPlus } from "@/components/icons";

const newId = () =>
  `u_${(typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Math.random())).replace(/-/g, "").slice(0, 8)}`;

export function DocEditor({
  doc,
  onChange,
  onChangeFrame,
  onRemoveSnapshot,
  snapshotBusy,
  canPickFrames,
}: {
  doc: DocV2;
  onChange: (next: DocV2) => void;
  onChangeFrame: (stepId: string) => void;
  onRemoveSnapshot: (stepId: string) => void;
  snapshotBusy: Record<string, true>;
  canPickFrames: boolean;
}) {
  const [announce, setAnnounce] = useState("");
  const [focusId, setFocusId] = useState<string | null>(null);

  const patchStep = (id: string, patch: Partial<DocStepV2>) =>
    onChange({ ...doc, steps: doc.steps.map((s) => (s.id === id ? { ...s, ...patch } : s)) });

  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= doc.steps.length) return;
    const steps = [...doc.steps];
    [steps[i], steps[j]] = [steps[j], steps[i]];
    onChange({ ...doc, steps });
    setAnnounce(`Step ${i + 1} moved ${dir < 0 ? "up" : "down"} to position ${j + 1}`);
  };

  const remove = (id: string) => {
    onChange({ ...doc, steps: doc.steps.filter((s) => s.id !== id) });
    setAnnounce("Step deleted");
  };

  const addAt = (i: number) => {
    const prev = doc.steps[i - 1];
    const next = doc.steps[i];
    const t = prev?.source.t_end ?? next?.source.t_start ?? 0;
    const step: DocStepV2 = {
      id: newId(),
      title: "",
      body: "",
      tip: null,
      snapshot: null,
      source: { graph_step_id: null, t_start: t, t_end: next?.source.t_start ?? t },
    };
    const steps = [...doc.steps];
    steps.splice(i, 0, step);
    onChange({ ...doc, steps });
    setFocusId(step.id);
  };

  const AddStep = ({ at }: { at: number }) => (
    <button
      type="button"
      onClick={() => addAt(at)}
      className="mx-auto flex items-center gap-1.5 rounded-full px-3 py-1 text-[12.5px] font-medium text-[var(--text-3)] transition-colors hover:bg-[var(--brand-soft)] hover:text-[var(--brand)]"
    >
      <IconPlus width={13} height={13} /> Add step
    </button>
  );

  return (
    <div>
      <span className="sr-only" aria-live="polite">
        {announce}
      </span>

      <input
        value={doc.title}
        onChange={(e) => onChange({ ...doc, title: e.target.value })}
        placeholder="Document title"
        aria-label="Document title"
        className="w-full rounded-md bg-transparent px-1.5 py-1 text-[28px] font-bold leading-tight tracking-tight text-[var(--text)] outline-none ring-[#1E8F8E]/30 placeholder:font-normal placeholder:text-[var(--text-3)] focus:bg-[var(--hover)] focus:ring-2"
      />

      <section className="mt-3">
        <AutosizeTextarea
          value={doc.overview}
          minRows={2}
          onChange={(e) => onChange({ ...doc, overview: e.target.value })}
          placeholder="What this guide covers, who it is for, and the end result."
          aria-label="Overview"
          className="text-[15px] leading-relaxed"
        />
        {doc.overview && /(\*\*|`)/.test(doc.overview) && (
          <p className="mt-1.5 px-1 text-[12px] text-[var(--text-3)]">
            Preview: <Inline text={doc.overview} />
          </p>
        )}
      </section>

      <section className="mt-7">
        <h2 className="eyebrow mb-2">Prerequisites</h2>
        <ListEditor
          items={doc.prerequisites}
          onChange={(prerequisites) => onChange({ ...doc, prerequisites })}
          placeholder="e.g. An admin account"
          addLabel="Add prerequisite"
        />
      </section>

      <section className="mt-7">
        <h2 className="eyebrow mb-2">Steps</h2>
        <ol className="flex flex-col gap-3">
          <AddStep at={0} />
          {doc.steps.map((s, i) => (
            <div key={s.id} className="flex flex-col gap-3">
              <StepCard
                step={s}
                index={i}
                total={doc.steps.length}
                busy={!!snapshotBusy[s.id]}
                canPickFrames={canPickFrames}
                autoFocus={focusId === s.id}
                onPatch={(p) => patchStep(s.id, p)}
                onMoveUp={() => move(i, -1)}
                onMoveDown={() => move(i, 1)}
                onDelete={() => remove(s.id)}
                onChangeFrame={() => onChangeFrame(s.id)}
                onRemoveSnapshot={() => onRemoveSnapshot(s.id)}
              />
              <AddStep at={i + 1} />
            </div>
          ))}
        </ol>
      </section>

      <section className="mt-7">
        <h2 className="eyebrow mb-2">Tips &amp; troubleshooting</h2>
        <ListEditor
          items={doc.tips}
          onChange={(tips) => onChange({ ...doc, tips })}
          placeholder="e.g. If the page does not refresh, press F5"
          addLabel="Add tip"
          icon={<IconLightbulb width={14} height={14} />}
        />
      </section>
    </div>
  );
}
