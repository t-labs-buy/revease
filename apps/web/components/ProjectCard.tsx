"use client";

import Link from "next/link";
import { useState } from "react";
import { mediaUrl, toggleFavorite, type Project, type Session } from "@/lib/api";

const GRADS = [
  "from-[#6d5dfb] to-[#a855f7]",
  "from-[#8b5cf6] to-[#ec4899]",
  "from-[#6366f1] to-[#06b6d4]",
  "from-[#f97316] to-[#ec4899]",
];

const mmss = (ms: number) =>
  `${String(Math.floor(ms / 60000)).padStart(2, "0")}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, "0")}`;

const fmtDate = (iso?: string) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};

function statusOf(s?: Session): { label: string; cls: string } {
  if (!s) return { label: "Active", cls: "bg-emerald-500/10 text-emerald-500 ring-emerald-500/20" };
  if (s.status === "ready") return { label: "Ready", cls: "bg-emerald-500/10 text-emerald-500 ring-emerald-500/20" };
  if (s.status === "processing" || s.status === "captured")
    return { label: "Processing", cls: "bg-[#6d5dfb]/10 text-[var(--brand-2)] ring-[#6d5dfb]/25" };
  if (s.status === "error") return { label: "Error", cls: "bg-red-500/10 text-red-500 ring-red-500/20" };
  return { label: "Active", cls: "bg-emerald-500/10 text-emerald-500 ring-emerald-500/20" };
}

/** Thumbnail project card (poster, duration, status, favorite star). */
export function ProjectCard({
  project,
  sessions,
  index = 0,
  className = "",
}: {
  project: Project;
  sessions: Session[]; // all sessions (filtered internally by project)
  index?: number;
  className?: string;
}) {
  const [fav, setFav] = useState(!!project.favorite);
  const mine = sessions.filter((s) => s.project_id === project.id);
  const latest = [...mine].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
  const st = statusOf(latest);

  return (
    <Link href={`/projects/${project.id}`} className={`card card-hover overflow-hidden ${className}`}>
      {/* thumbnail */}
      <div className="relative h-36 bg-gradient-to-br from-[#1c1c2e] to-[#2b2b45]">
        {latest?.poster ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={mediaUrl(latest.poster)} alt={project.name} className="h-full w-full object-cover" />
        ) : (
          <div className={`h-full w-full bg-gradient-to-br ${GRADS[index % GRADS.length]} opacity-70`} />
        )}
        <span className="absolute inset-0 flex items-center justify-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-white/90 pl-0.5 text-[#6d5dfb] shadow-lg">
            ▶
          </span>
        </span>
        {latest?.duration_ms ? (
          <span className="absolute bottom-2 right-2 rounded-md bg-black/70 px-1.5 py-0.5 text-[11px] font-medium text-white">
            {mmss(latest.duration_ms)}
          </span>
        ) : null}
      </div>
      {/* body */}
      <div className="p-4">
        <div className="truncate font-semibold text-[var(--text)]">{project.name}</div>
        <div className="mt-1 text-xs text-[var(--text-2)]">
          {mine.length} capture{mine.length === 1 ? "" : "s"} • {fmtDate(project.created_at)}
        </div>
        <span className={`badge mt-2.5 px-2.5 py-0.5 ring-1 ring-inset ${st.cls}`}>{st.label}</span>
        <div className="mt-3 flex items-center justify-between border-t border-[var(--border)] pt-2.5 text-[12px] text-[var(--text-3)]">
          <span className="inline-flex items-center gap-1.5">🗂 Project</span>
          <span className="flex items-center gap-2">
            <button
              title={fav ? "Unstar" : "Star — pinned first"}
              onClick={(e) => {
                e.preventDefault();
                setFav((v) => !v); // optimistic
                toggleFavorite(project.id).catch(() => setFav((v) => !v));
              }}
              className={fav ? "text-amber-400" : "hover:text-[var(--brand-2)]"}
            >
              {fav ? "★" : "☆"}
            </button>
            <button title="More" onClick={(e) => e.preventDefault()} className="hover:text-[var(--text)]">
              ⋮
            </button>
          </span>
        </div>
      </div>
    </Link>
  );
}
