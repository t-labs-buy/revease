"use client";

import { useEffect, useState } from "react";
import {
  listAllShares,
  listProjects,
  revokeShare,
  setShareDownload,
  shareLink,
  type ListScope,
  type Project,
  type Share,
} from "@/lib/api";
import { Badge, EmptyState } from "@/components/ui";
import { ScopeToggle } from "@/components/ScopeToggle";

export default function SharedPage() {
  const [scope, setScope] = useState<ListScope>("mine");
  const [shares, setShares] = useState<Share[]>([]);
  const [projects, setProjects] = useState<Record<string, Project>>({});
  const [error, setError] = useState<string | null>(null);

  async function load(s: ListScope = scope) {
    try {
      const [rows, ps] = await Promise.all([listAllShares(s), listProjects(s)]);
      setShares(rows);
      setProjects(Object.fromEntries(ps.map((p) => [p.id, p])));
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    void load(scope);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope]);

  async function toggleDownload(share: Share, next: boolean) {
    // optimistic update, then reconcile with the server
    setShares((prev) =>
      prev.map((s) => (s.token === share.token ? { ...s, allow_download: next } : s)),
    );
    try {
      const updated = await setShareDownload(share.token, next);
      setShares((prev) => prev.map((s) => (s.token === updated.token ? updated : s)));
    } catch (e) {
      setError(String(e));
      void load();
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Shared Pages</h1>
          <p className="text-sm text-zinc-500">Public links to your videos and documents.</p>
        </div>
        <ScopeToggle scope={scope} onChange={setScope} mineLabel="My links" allLabel="All links" />
      </div>

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
              <li key={s.token} className="card flex flex-wrap items-center gap-3 px-4 py-3">
                <Badge tone={s.kind === "video" ? "violet" : "zinc"}>{s.kind}</Badge>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-zinc-100">
                    {projects[s.project_id]?.name ?? s.project_id}
                  </div>
                  <a
                    href={shareLink(s.token)}
                    target="_blank"
                    rel="noreferrer"
                    className="truncate text-xs text-[#1E8F8E] hover:text-[#1E8F8E]"
                  >
                    {shareLink(s.token)}
                  </a>
                </div>
                {s.kind === "video" && (
                  <label
                    className="flex items-center gap-2 text-xs text-zinc-300"
                    title="Show a Download button on the shared page"
                  >
                    <input
                      type="checkbox"
                      checked={s.allow_download}
                      onChange={(e) => void toggleDownload(s, e.target.checked)}
                      className="accent-[#1E8F8E]"
                    />
                    Download
                  </label>
                )}
                <a
                  href={shareLink(s.token)}
                  target="_blank"
                  rel="noreferrer"
                  className="btn btn-secondary btn-sm"
                >
                  Open
                </a>
                <button
                  onClick={() => revokeShare(s.token).then(() => load())}
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
