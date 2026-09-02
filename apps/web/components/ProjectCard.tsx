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
  onDelete,
  selectable = false,
  selected = false,
  onToggleSelect,
  onFavoriteChange,
}: {
  project: Project;
  sessions: Session[]; // all sessions (filtered internally by project)
  index?: number;
  className?: string;
  onDelete?: (id: string) => void; // request deletion (the page shows the styled confirm)
  selectable?: boolean; // multi-select mode: clicking toggles selection instead of opening
  selected?: boolean;
  onToggleSelect?: (id: string) => void;
  onFavoriteChange?: (id: string, favorite: boolean) => void; // keep the page's list in sync
}) {
  const [fav, setFav] = useState(!!project.favorite);
  const mine = sessions.filter((s) => s.project_id === project.id);
  const latest = [...mine].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
  const st = statusOf(latest);

  return (
    <Link
      href={`/projects/${project.id}`}
      onClick={(e) => {
        if (selectable) {
          e.preventDefault();
          onToggleSelect?.(project.id);
        }
      }}
      className={`card card-hover relative overflow-hidden ${
        selected ? "ring-2 ring-[#6d5dfb]" : ""
      } ${className}`}
    >
      {/* selection check */}
      {selectable && (
        <span
          className={`absolute left-2.5 top-2.5 z-10 flex h-6 w-6 items-center justify-center rounded-full text-[13px] shadow ${
            selected
              ? "bg-[#6d5dfb] text-white"
              : "border border-white/70 bg-black/30 text-transparent backdrop-blur-sm"
          }`}
        >
          ✓
        </span>
      )}
      {/* thumbnail */}
      <div className="relative aspect-video bg-gradient-to-br from-[#1c1c2e] to-[#2b2b45]">
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
      <div className="p-5">
        <div className="truncate text-[17px] font-semibold text-[var(--text)]">{project.name}</div>
        <div className="mt-1 text-sm text-[var(--text-2)]">
          {mine.length} capture{mine.length === 1 ? "" : "s"} • {fmtDate(project.created_at)}
        </div>
        <span className={`badge mt-2.5 px-2.5 py-0.5 ring-1 ring-inset ${st.cls}`}>{st.label}</span>
        <div className="mt-3.5 flex items-center justify-between border-t border-[var(--border)] pt-3 text-sm text-[var(--text-3)]">
          {/* owner label — present only for admins browsing all spaces */}
          {project.owner_email ? (
            <span className="inline-flex min-w-0 items-center gap-1.5" title={project.owner_email}>
              👤 <span className="truncate">{project.owner_name || project.owner_email}</span>
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5">🗂 Project</span>
          )}
          <span className="flex items-center gap-1">
            <button
              title={fav ? "Unstar" : "Star — pinned first"}
              onClick={(e) => {
                e.preventDefault();
                const next = !fav;
                setFav(next); // optimistic
                onFavoriteChange?.(project.id, next);
                toggleFavorite(project.id).catch(() => {
                  setFav(!next);
                  onFavoriteChange?.(project.id, !next);
                });
              }}
              className={`rounded-lg p-1.5 text-2xl leading-none transition-colors ${
                fav ? "text-amber-400" : "hover:text-[var(--brand-2)]"
              }`}
            >
              {fav ? "★" : "☆"}
            </button>
            {onDelete && !selectable && (
              <button
                title="Remove project"
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  onDelete(project.id);
                }}
                className="rounded-lg p-1.5 text-lg leading-none transition-colors hover:text-red-500"
              >
                🗑
              </button>
            )}
          </span>
        </div>
      </div>
    </Link>
  );
}
