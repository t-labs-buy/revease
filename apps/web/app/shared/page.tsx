"use client";

import { useEffect, useState } from "react";
import {
  listAllShares,
  listProjects,
  revokeShare,
  shareLink,
  type Project,
  type Share,
} from "@/lib/api";
import { Badge, EmptyState } from "@/components/ui";

export default function SharedPage() {
  const [shares, setShares] = useState<Share[]>([]);
  const [projects, setProjects] = useState<Record<string, Project>>({});
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const [s, ps] = await Promise.all([listAllShares(), listProjects()]);
      setShares(s);
      setProjects(Object.fromEntries(ps.map((p) => [p.id, p])));
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <h1 className="text-2xl font-semibold tracking-tight">Shared Pages</h1>
      <p className="text-sm text-zinc-500">Public links to your videos and documents.</p>

      {error && (
        <p className="mt-4 rounded-lg border border-red-900/60 bg-red-950/30 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      <div className="mt-8">
        {shares.length === 0 && !error ? (
          <EmptyState
            title="No shared links yet"
            hint="Open a video or document and hit Share to create a public link."
          />
        ) : (
          <ul className="space-y-2.5">
            {shares.map((s) => (
              <li key={s.token} className="card flex items-center gap-3 px-4 py-3">
                <Badge tone={s.kind === "video" ? "violet" : "zinc"}>{s.kind}</Badge>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-zinc-100">
                    {projects[s.project_id]?.name ?? s.project_id}
                  </div>
                  <a
                    href={shareLink(s.token)}
                    target="_blank"
                    rel="noreferrer"
                    className="truncate text-xs text-violet-400 hover:text-violet-300"
                  >
                    {shareLink(s.token)}
                  </a>
                </div>
                <a
                  href={shareLink(s.token)}
                  target="_blank"
                  rel="noreferrer"
                  className="btn btn-secondary btn-sm"
                >
                  Open
                </a>
                <button
                  onClick={() => revokeShare(s.token).then(load)}
                  className="btn btn-ghost btn-sm text-red-300"
                >
                  Revoke
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
