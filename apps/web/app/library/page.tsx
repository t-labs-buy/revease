"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { listProjects, listSessions, type Project, type Session } from "@/lib/api";
import { ProjectCard } from "@/components/ProjectCard";
import { EmptyState } from "@/components/ui";

type Filter = "all" | "starred" | "ready" | "processing";
const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "starred", label: "★ Starred" },
  { key: "ready", label: "Ready" },
  { key: "processing", label: "Processing" },
];

export default function LibraryPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    Promise.all([listSessions(), listProjects()])
      .then(([s, ps]) => {
        setSessions(s);
        setProjects(ps); // API sorts starred first
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, []);

  const latestStatus = (pid: string) =>
    sessions
      .filter((s) => s.project_id === pid)
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0]?.status;

  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    return projects.filter((p) => {
      if (t && !p.name.toLowerCase().includes(t)) return false;
      if (filter === "starred") return !!p.favorite;
      if (filter === "ready") return latestStatus(p.id) === "ready";
      if (filter === "processing")
        return ["processing", "captured"].includes(latestStatus(p.id) ?? "");
      return true;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects, sessions, q, filter]);

  return (
    <main className="mx-auto max-w-6xl px-8 py-10">
      {/* header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-[var(--text)]">Library</h1>
          <p className="mt-1.5 text-[15px] text-[var(--text-2)]">
            All your projects and captures — starred first.
          </p>
        </div>
        <Link href="/library/packages" className="btn btn-secondary">
          🎨 Brand Packages
        </Link>
      </div>

      {/* search + filters */}
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-sm">
          <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-3)]">
            ⌕
          </span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search projects…"
            className="input rounded-full pl-9"
          />
        </div>
        <div className="flex items-center gap-1.5">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors ${
                filter === f.key
                  ? "border-[#6d5dfb] bg-[#6d5dfb]/10 text-[var(--brand-2)]"
                  : "border-[var(--border)] bg-[var(--card)] text-[var(--text-2)] hover:text-[var(--text)]"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <p className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </p>
      )}

      {/* grid */}
      {filtered.length === 0 && !error ? (
        <div className="mt-10">
          <EmptyState
            title={q || filter !== "all" ? "Nothing matches" : "Your library is empty"}
            hint={
              q || filter !== "all"
                ? "Try a different search or filter."
                : "Record your screen or upload a video from the Home page to get started."
            }
          />
        </div>
      ) : (
        <div className="mt-8 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((p, i) => (
            <ProjectCard key={p.id} project={p} sessions={sessions} index={i} />
          ))}
        </div>
      )}
    </main>
  );
}
