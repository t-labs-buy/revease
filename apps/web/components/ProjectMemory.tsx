"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getMemory, type Memory } from "@/lib/api";
import { Badge } from "@/components/ui";

export function ProjectMemory({ projectId }: { projectId: string }) {
  const [mem, setMem] = useState<Memory | null>(null);

  useEffect(() => {
    getMemory(projectId)
      .then(setMem)
      .catch(() => {});
  }, [projectId]);

  // only show when there's a prior version to diff against
  if (!mem || !mem.has_prior) return null;
  const { summary } = mem;
  const changedSteps = mem.steps.filter((s) => s.status !== "unchanged");

  return (
    <section className="card border-violet-500/30 bg-gradient-to-br from-violet-600/10 to-transparent p-5">
      <div className="flex items-center justify-between">
        <div>
          <div className="label mb-1">Project memory</div>
          <div className="text-sm text-zinc-300">
            You re-recorded this workflow (v{mem.from_version} → v{mem.to_version}).
          </div>
        </div>
        <Link href={`/projects/${projectId}/video`} className="btn btn-primary btn-sm">
          Regenerate changed →
        </Link>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {summary.added > 0 && <Badge tone="green">{summary.added} added</Badge>}
        {summary.changed > 0 && <Badge tone="amber">{summary.changed} changed</Badge>}
        {summary.removed > 0 && <Badge tone="red">{summary.removed} removed</Badge>}
        <Badge tone="zinc">{summary.unchanged} unchanged</Badge>
      </div>

      {changedSteps.length > 0 && (
        <ul className="mt-3 space-y-1.5 text-sm">
          {changedSteps.slice(0, 8).map((s) => (
            <li key={s.id} className="flex items-center gap-2 text-zinc-300">
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  s.status === "added" ? "bg-emerald-500" : "bg-amber-400"
                }`}
              />
              <span className="text-xs uppercase tracking-wide text-zinc-500">{s.status}</span>
              {s.target}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-zinc-500">
        Only the changed steps regenerate — your edits on unchanged steps are preserved.
      </p>
    </section>
  );
}
