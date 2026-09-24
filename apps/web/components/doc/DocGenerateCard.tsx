"use client";

import { useEffect, useState } from "react";
import { listSkills, type Skill } from "@/lib/api";
import { AutosizeTextarea } from "@/components/doc/AutosizeTextarea";
import { IconDoc, IconSparkles } from "@/components/icons";
import { Spinner } from "@/components/ui";
import type { GenerateOpts } from "@/components/doc/useDocumentState";

/** Doc-targeted skills the user owns (a style preset for the writer). */
export function useDocSkills(): Skill[] {
  const [skills, setSkills] = useState<Skill[]>([]);
  useEffect(() => {
    listSkills("mine")
      .then((s) => setSkills(s.filter((x) => x.target === "doc")))
      .catch(() => setSkills([]));
  }, []);
  return skills;
}

export function GenerateOptions({
  value,
  onChange,
  skills,
}: {
  value: GenerateOpts;
  onChange: (v: GenerateOpts) => void;
  skills: Skill[];
}) {
  return (
    <div className="flex flex-col gap-3">
      <label className="block">
        <span className="mb-1 block text-[12.5px] font-medium text-[var(--text-2)]">Anything to emphasise? (optional)</span>
        <AutosizeTextarea
          value={value.instruction ?? ""}
          minRows={2}
          onChange={(e) => onChange({ ...value, instruction: e.target.value })}
          placeholder="e.g. Audience is new hires; keep steps short and add a troubleshooting tip"
        />
      </label>
      {skills.length > 0 && (
        <label className="block">
          <span className="mb-1 block text-[12.5px] font-medium text-[var(--text-2)]">Style</span>
          <select
            className="input"
            value={value.skill_id ?? ""}
            onChange={(e) => onChange({ ...value, skill_id: e.target.value || undefined })}
          >
            <option value="">Default style</option>
            {skills.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  );
}

export function DocGenerateCard({
  onGenerate,
  busy,
  error,
}: {
  onGenerate: (opts: GenerateOpts) => void | Promise<void>;
  busy?: boolean;
  error?: string | null;
}) {
  const skills = useDocSkills();
  const [opts, setOpts] = useState<GenerateOpts>({});
  return (
    <section className="card mx-auto max-w-2xl p-6 sm:p-8">
      <span className="flex h-11 w-11 items-center justify-center rounded-lg bg-[var(--brand-soft)] text-[var(--brand)]">
        <IconDoc width={22} height={22} />
      </span>
      <h2 className="mt-4 text-[20px] font-semibold tracking-tight text-[var(--text)]">Generate documentation</h2>
      <p className="mt-1.5 text-[14px] leading-relaxed text-[var(--text-2)]">
        Claude reads the recording and its transcript, writes a step-by-step guide with an overview,
        prerequisites and tips, and captures an annotated screenshot for every step.
      </p>
      <div className="mt-5">
        <GenerateOptions value={opts} onChange={setOpts} skills={skills} />
      </div>
      {error && (
        <p className="mt-4 rounded-lg border border-[#D9534F]/30 bg-[#D9534F]/10 px-3 py-2 text-sm text-[var(--error)]">
          {error}
        </p>
      )}
      <button
        type="button"
        onClick={() => void onGenerate({ instruction: opts.instruction?.trim() || undefined, skill_id: opts.skill_id })}
        disabled={busy}
        className="btn btn-primary mt-5"
      >
        {busy ? <Spinner /> : <IconSparkles width={16} height={16} />} Generate documentation
      </button>
    </section>
  );
}
