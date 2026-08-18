"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { getProject, listSessions, type Project, type Session } from "@/lib/api";
import { Recorder } from "@/components/Recorder";
import { Uploader } from "@/components/Uploader";
import { CaptureCard } from "@/components/CaptureCard";
import { EmptyState } from "@/components/ui";
import { IconArrowRight, IconDoc, IconUpload, IconVideo } from "@/components/icons";

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
    <main className="min-h-screen bg-[var(--bg)]">
      <div className="mx-auto max-w-[1600px] px-8 py-10">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-[var(--text-2)] transition-colors hover:text-[var(--text)]"
        >
          ← Projects
        </Link>

        <section className="animate-fade-in mt-4 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[34px] font-bold leading-[1.15] tracking-tight text-[var(--text)]">
              {project?.name ?? "Project"}
            </h1>
            <p className="mt-1.5 text-[15px] text-[var(--text-2)]">
              {sessions.length} capture{sessions.length === 1 ? "" : "s"}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href={`/projects/${id}/document`}
              className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-2.5 text-sm font-semibold text-[var(--text)] shadow-[var(--shadow-card)] transition-colors hover:bg-[var(--hover)]"
            >
              <IconDoc width={15} height={15} /> Document
            </Link>
            <Link
              href={`/projects/${id}/video`}
              className={`inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold shadow-sm transition-transform duration-200 hover:scale-[1.03] ${
                hasGraph
                  ? "bg-[#7C3AED] text-white"
                  : "border border-[var(--border)] bg-[var(--card)] text-[var(--text)]"
              }`}
            >
              Video editor <IconArrowRight width={15} height={15} />
            </Link>
          </div>
        </section>

        {error && (
          <p className="mt-6 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
            {error}
          </p>
        )}

        {/* Capture panel — shelved. Both cards are drawn but dimmed and inert,
            with an "Upcoming" chip on top that stays at full contrast rather
            than fading along with the card behind it. */}
        <div className="mt-10 grid gap-6 md:grid-cols-2">
          <div aria-disabled="true" className="relative cursor-not-allowed select-none">
            <div className="pointer-events-none h-full opacity-40">
              <div className="card h-full p-6">
                <div className="flex items-start gap-4">
                  <span className="flex h-12 w-12 flex-none items-center justify-center rounded-2xl bg-[#7C3AED]/10 text-[#7C3AED]">
                    <IconVideo width={20} height={20} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <h2 className="text-[17px] font-semibold text-[var(--text)]">Record screen</h2>
                    <p className="mt-0.5 text-sm leading-snug text-[var(--text-2)]">
                      Capture a walkthrough straight from your browser.
                    </p>
                  </div>
                </div>
                <div className="mt-5">
                  <Recorder projectId={id} onDone={refresh} />
                </div>
              </div>
            </div>
            <span className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <span className="rounded-full border border-[var(--border)] bg-[var(--card)]/95 px-6 py-3 text-lg font-semibold tracking-tight text-[var(--text)] shadow-[var(--shadow-card-hover)] backdrop-blur-sm">
                Upcoming
              </span>
            </span>
          </div>

          <div aria-disabled="true" className="relative cursor-not-allowed select-none">
            <div className="pointer-events-none h-full opacity-40">
              <div className="card h-full p-6">
                <div className="flex items-start gap-4">
                  <span className="flex h-12 w-12 flex-none items-center justify-center rounded-2xl bg-[#0EA5E9]/10 text-[#0EA5E9]">
                    <IconUpload width={20} height={20} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <h2 className="text-[17px] font-semibold text-[var(--text)]">Upload a video</h2>
                    <p className="mt-0.5 text-sm leading-snug text-[var(--text-2)]">
                      Already have a recording? Bring it in as an mp4 or webm.
                    </p>
                  </div>
                </div>
                <div className="mt-5">
                  <Uploader projectId={id} onDone={refresh} />
                </div>
              </div>
            </div>
            <span className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <span className="rounded-full border border-[var(--border)] bg-[var(--card)]/95 px-6 py-3 text-lg font-semibold tracking-tight text-[var(--text)] shadow-[var(--shadow-card-hover)] backdrop-blur-sm">
                Upcoming
              </span>
            </span>
          </div>
        </div>

        {/* Captures */}
        <div className="mt-12 flex items-center justify-between">
          <h2 className="text-[28px] font-semibold tracking-tight text-[var(--text)]">Captures</h2>
        </div>
        {sessions.length === 0 && !error ? (
          <div className="mt-6">
            <EmptyState
              title="No captures yet"
              hint="Record your screen or upload a video above — it'll appear here and process into a Workflow Graph."
            />
          </div>
        ) : (
          <div className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {sessions.map((s) => (
              <CaptureCard key={s.id} session={s} href={`/projects/${id}/sessions/${s.id}`} />
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
