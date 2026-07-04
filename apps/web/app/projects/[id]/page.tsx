"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { getProject, listSessions, type Project, type Session } from "@/lib/api";
import { Recorder } from "@/components/Recorder";
import { Uploader } from "@/components/Uploader";
import { CaptureCard } from "@/components/CaptureCard";
import { ProjectMemory } from "@/components/ProjectMemory";
import { EmptyState } from "@/components/ui";

export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [project, setProject] = useState<Project | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [p, s] = await Promise.all([getProject(id), listSessions(id)]);
      setProject(p);
      setSessions(s);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [id]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const hasGraph = sessions.some((s) => s.status === "ready");

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <Link href="/" className="btn btn-ghost btn-sm -ml-2">
        ← Projects
      </Link>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {project?.name ?? "Project"}
          </h1>
          <p className="text-sm text-zinc-500">
            {sessions.length} capture{sessions.length === 1 ? "" : "s"}
          </p>
        </div>
        <div className="flex gap-2">
          <Link href={`/projects/${id}/document`} className="btn btn-secondary">
            Document
          </Link>
          <Link
            href={`/projects/${id}/video`}
            className={`btn ${hasGraph ? "btn-primary" : "btn-secondary"}`}
          >
            Video editor →
          </Link>
        </div>
      </div>

      {error && (
        <p className="mt-4 rounded-lg border border-red-900/60 bg-red-950/30 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      {/* Project memory (re-record diff) */}
      <div className="mt-6">
        <ProjectMemory projectId={id} />
      </div>

      {/* Capture panel */}
      <section className="mt-6 grid gap-4 md:grid-cols-2">
        <div className="card p-5">
          <div className="label mb-3">Record screen</div>
          <Recorder projectId={id} onDone={refresh} />
        </div>
        <div className="card p-5">
          <div className="label mb-3">Upload a video</div>
          <Uploader projectId={id} onDone={refresh} />
        </div>
      </section>

      {/* Captures */}
      <section className="mt-10">
        <div className="label mb-3">Captures</div>
        {sessions.length === 0 && !error ? (
          <EmptyState
            title="No captures yet"
            hint="Record your screen or upload a video above — it'll appear here and process into a Workflow Graph."
          />
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {sessions.map((s) => (
              <CaptureCard
                key={s.id}
                session={s}
                href={`/projects/${id}/sessions/${s.id}`}
              />
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
