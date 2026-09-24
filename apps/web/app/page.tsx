"use client";

/**
 * The dashboard. Laid out as a workspace rather than a landing page: a compact
 * hero, a task-oriented "Create content" panel, then a grid of overview
 * metrics, recent activity, the most recent project to resume, and a project
 * list. Everything shown is derived from real projects/sessions — no
 * placeholder numbers — and the header search filters the lists below.
 *
 * Shelved features (the knowledge base) are shown inert with a small "Beta"
 * pill rather than a "Coming soon" overlay, so the page doesn't advertise what
 * it can't do yet.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { createPortal } from "react-dom";
import { listArticles, listProjects, listSessions, mediaUrl, type Project, type Session } from "@/lib/api";
import { CaptureModal, type CaptureIntent } from "@/components/CaptureModal";
import { EmptyState } from "@/components/ui";
import { useTopBarSlot } from "@/components/TopBar";
import { useAuth } from "@/contexts/AuthContext";
import {
  IconArrowRight,
  IconChevronRight,
  IconDoc,
  IconFolder,
  IconLibrary,
  IconPlay,
  IconPlus,
  IconSearch,
  IconSparkles,
  IconUpload,
  IconVideo,
} from "@/components/icons";

function timeGreeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

const mmss = (ms: number) =>
  `${String(Math.floor(ms / 60000)).padStart(2, "0")}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, "0")}`;

/** API timestamps are UTC but carry no zone marker (SQLite drops it) — without
 *  the "Z" the browser reads them as local time and everything looks ~5.5h old. */
const toMs = (iso?: string) => {
  if (!iso) return 0;
  const utc = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + "Z";
  const d = new Date(utc).getTime();
  return isNaN(d) ? 0 : d;
};

const relTime = (iso?: string) => {
  const d = toMs(iso);
  if (!d) return "recently";
  const s = Math.max(1, Math.floor((Date.now() - d) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const day = Math.floor(h / 24);
  if (day === 1) return "yesterday";
  if (day < 30) return `${day} days ago`;
  return `${Math.floor(day / 30)} mo ago`;
};

const pad2 = (n: number) => String(n).padStart(2, "0");

const STATUS_LABEL: Record<string, string> = {
  ready: "Ready to edit",
  processing: "Processing",
  captured: "Queued",
  error: "Needs attention",
};

/** Small section header: eyebrow label on the left, optional link on the right. */
function SectionHead({ label, href, linkText = "View all" }: { label: string; href?: string; linkText?: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="eyebrow">{label}</span>
      {href && (
        <Link href={href} className="inline-flex items-center gap-1 text-[13px] font-medium text-[var(--brand)] hover:underline">
          {linkText} <IconArrowRight width={13} height={13} />
        </Link>
      )}
    </div>
  );
}

function BetaPill() {
  return (
    <span className="rounded bg-[var(--hover)] px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-[var(--text-3)]">
      Beta
    </span>
  );
}

export default function Home() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [kbCount, setKbCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<CaptureIntent | null>(null);
  const [greeting, setGreeting] = useState("Welcome");
  const [q, setQ] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const topBarSlot = useTopBarSlot();
  const { user } = useAuth();
  // First name if they gave one, else the email's local part — never "User".
  const displayName = (user?.name?.trim().split(/\s+/)[0] || user?.email?.split("@")[0]) ?? "";

  useEffect(() => setGreeting(timeGreeting()), []);
  useEffect(() => {
    Promise.all([listSessions(), listProjects()])
      .then(([s, ps]) => {
        setSessions(s);
        setProjects(ps);
      })
      .catch((e) => setError(String(e)));
    // Knowledge base count is a nice-to-have stat; don't surface its errors on the homepage.
    listArticles()
      .then((a) => setKbCount(a.length))
      .catch(() => setKbCount(0));
  }, []);

  // ⌘K / Ctrl+K focuses search
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const open = (intent: CaptureIntent) => setModal(intent);

  // A project is a "Document" when one has actually been generated for it.
  const isDocProject = (p: Project) => !!p.has_document;

  // ---- derived data -------------------------------------------------------

  const byProject = useMemo(() => {
    const m = new Map<string, Session[]>();
    for (const s of sessions) m.set(s.project_id, [...(m.get(s.project_id) ?? []), s]);
    for (const list of m.values()) list.sort((a, b) => toMs(b.created_at) - toMs(a.created_at));
    return m;
  }, [sessions]);

  const latestOf = (p: Project) => byProject.get(p.id)?.[0];
  const touchedAt = (p: Project) => Math.max(toMs(p.created_at), toMs(latestOf(p)?.created_at));

  const term = q.trim().toLowerCase();
  const matches = (name: string) => !term || name.toLowerCase().includes(term);

  const recentProjects = useMemo(
    () => [...projects].filter((p) => matches(p.name)).sort((a, b) => touchedAt(b) - touchedAt(a)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [projects, byProject, term],
  );

  // One row per session (a video) plus one per generated document, newest first.
  const activity = useMemo(() => {
    const names = new Map(projects.map((p) => [p.id, p.name]));
    const rows: { key: string; title: string; kind: string; at: string; href: string }[] = [];
    for (const s of sessions) {
      const title = names.get(s.project_id);
      if (!title) continue;
      rows.push({ key: `s-${s.id}`, title, kind: "Video", at: s.created_at, href: `/projects/${s.project_id}` });
    }
    for (const p of projects) {
      if (isDocProject(p))
        rows.push({ key: `d-${p.id}`, title: p.name, kind: "Document", at: p.created_at, href: `/projects/${p.id}/document` });
      if (!byProject.has(p.id))
        rows.push({ key: `p-${p.id}`, title: p.name, kind: "Project", at: p.created_at, href: `/projects/${p.id}` });
    }
    return rows.filter((r) => matches(r.title)).sort((a, b) => toMs(b.at) - toMs(a.at)).slice(0, 6);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects, sessions, byProject, term]);

  // The most recently touched project that has a capture — the thing to resume.
  const resume = useMemo(() => {
    const p = [...projects].filter((p) => byProject.has(p.id)).sort((a, b) => touchedAt(b) - touchedAt(a))[0];
    return p ? { project: p, session: latestOf(p)! } : null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects, byProject]);

  const documentsCount = projects.filter(isDocProject).length;

  const METRICS = [
    { label: "Projects", value: projects.length, href: "/library" },
    { label: "Videos", value: sessions.length, href: "/library?kind=video" },
    { label: "Documents", value: documentsCount, href: "/library?kind=document" },
    { label: "Knowledge items", value: kbCount, soon: true },
  ];

  const CREATE: { title: string; desc: string; icon: JSX.Element; onClick: () => void; soon?: boolean }[] = [
    {
      title: "Record screen",
      desc: "Capture your screen and microphone. AI handles the rest.",
      icon: <IconVideo width={22} height={22} />,
      onClick: () => open("record"),
    },
    {
      title: "Create video",
      desc: "Polished video with AI voiceover, auto-zoom and captions.",
      icon: <IconSparkles width={22} height={22} />,
      onClick: () => open("video"),
    },
    {
      title: "Generate document",
      desc: "Step-by-step guides and SOPs from your captures.",
      icon: <IconDoc width={22} height={22} />,
      onClick: () => open("doc"),
    },
  ];

  const QUICK: { label: string; icon: JSX.Element; onClick?: () => void; href?: string; soon?: boolean }[] = [
    { label: "Record", icon: <IconPlus width={15} height={15} />, onClick: () => open("record") },
    { label: "Upload", icon: <IconUpload width={15} height={15} />, onClick: () => open("upload") },
    { label: "Create video", icon: <IconPlay width={13} height={13} />, onClick: () => open("video") },
    { label: "Document", icon: <IconDoc width={15} height={15} />, onClick: () => open("doc") },
    { label: "Open library", icon: <IconLibrary width={15} height={15} />, href: "/library" },
  ];

  return (
    <main className="min-h-full">
      {modal && <CaptureModal intent={modal} onClose={() => setModal(null)} />}

      {/* Search belongs to this page (it filters the lists below) but is shown in
          the shared header, so it renders into the header's slot. */}
      {topBarSlot &&
        createPortal(
          <>
            <IconSearch
              width={15}
              height={15}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-3)]"
            />
            <input
              ref={searchRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search projects, videos, documents..."
              className="input h-9 pl-9 pr-12"
            />
            <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 rounded border border-[var(--border)] bg-[var(--hover)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--text-3)]">
              ⌘K
            </span>
          </>,
          topBarSlot,
        )}

      <div className="mx-auto max-w-[1440px] px-5 py-7 md:px-8">
        {/* ---- hero -------------------------------------------------------- */}
        <section className="animate-fade-in relative overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] px-6 py-6 md:px-8">
          {/* Tarento geometry: two angled planes, kept faint so it reads as texture */}
          <div aria-hidden className="pointer-events-none absolute inset-y-0 right-0 hidden w-[42%] md:block">
            <div className="tarento-lines absolute inset-0 opacity-70" />
            <div className="absolute -right-24 -top-10 h-[240%] w-40 -rotate-[28deg] bg-[var(--navy)] opacity-[0.06]" />
            <div className="absolute -right-2 -top-10 h-[240%] w-24 -rotate-[28deg] bg-[var(--brand)] opacity-[0.10]" />
            <div className="absolute inset-0 bg-gradient-to-r from-[var(--card)] via-[var(--card)] to-transparent" />
          </div>
          <div className="relative">
            <span className="eyebrow">Welcome back</span>
            <h1 className="mt-1.5 text-[28px] font-bold leading-tight tracking-tight text-[var(--text)] md:text-[30px]">
              {greeting}, {displayName} <span className="align-middle">👋</span>
            </h1>
            <p className="mt-1.5 max-w-lg text-[14px] text-[var(--text-2)]">
              Create, capture and share knowledge with AI-powered workflows.
            </p>
            <div className="mt-5 flex flex-wrap items-center gap-2.5">
              <button onClick={() => open("record")} className="btn btn-primary">
                <IconPlus width={16} height={16} /> Create content
              </button>
              <Link href="/library" className="btn btn-secondary">
                Explore library
              </Link>
            </div>
          </div>
        </section>

        {error && (
          <p className="mt-4 rounded-lg border border-[#D9534F]/30 bg-[#D9534F]/10 px-3 py-2 text-sm text-[var(--error)]">
            {error}
          </p>
        )}

        {/* ---- create content + quick actions ------------------------------- */}
        <div className="mt-5 grid gap-5 lg:grid-cols-3">
          <section className="card animate-fade-in p-6 lg:col-span-2" style={{ animationDelay: "40ms" }}>
            <SectionHead label="Create content" />
            <h2 className="mt-1.5 text-[18px] font-semibold tracking-tight text-[var(--text)]">
              What do you want to create?
            </h2>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {CREATE.map((c) => (
                <button
                  key={c.title}
                  onClick={c.soon ? undefined : c.onClick}
                  disabled={c.soon}
                  aria-disabled={c.soon ? "true" : undefined}
                  title={c.soon ? "Coming soon" : undefined}
                  className={`group flex flex-col items-start gap-3 rounded-lg border p-4 text-left transition-colors ${
                    c.soon
                      ? "cursor-not-allowed border-dashed border-[var(--border)] opacity-60"
                      : "border-[var(--border)] hover:border-[var(--brand)] hover:bg-[var(--brand-soft)]"
                  }`}
                >
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--brand-soft)] text-[var(--brand)]">
                    {c.icon}
                  </span>
                  <span>
                    <span className="flex items-center gap-2 text-[15px] font-semibold text-[var(--text)]">
                      {c.title}
                      {c.soon && <BetaPill />}
                    </span>
                    <span className="mt-1 block text-[13px] leading-snug text-[var(--text-2)]">{c.desc}</span>
                  </span>
                </button>
              ))}
            </div>
          </section>

          <section className="card animate-fade-in p-6" style={{ animationDelay: "80ms" }}>
            <SectionHead label="Quick actions" />
            <div className="mt-4 flex flex-wrap gap-2">
              {QUICK.map((t) => {
                const cls = "btn btn-secondary btn-sm h-9 gap-1.5 px-3 text-[13px]";
                if (t.soon)
                  return (
                    <span key={t.label} aria-disabled="true" title="Coming soon" className={`${cls} cursor-not-allowed opacity-50`}>
                      {t.icon} {t.label} <BetaPill />
                    </span>
                  );
                return t.href ? (
                  <Link key={t.label} href={t.href} className={cls}>
                    {t.icon} {t.label}
                  </Link>
                ) : (
                  <button key={t.label} onClick={t.onClick} className={cls}>
                    {t.icon} {t.label}
                  </button>
                );
              })}
            </div>
            <p className="mt-4 text-[12.5px] leading-relaxed text-[var(--text-3)]">
              Press <kbd className="rounded border border-[var(--border)] bg-[var(--hover)] px-1 text-[11px]">⌘K</kbd> to search
              across everything you&apos;ve made.
            </p>
          </section>
        </div>

        {/* ---- overview + recent activity ---------------------------------- */}
        <div className="mt-5 grid gap-5 lg:grid-cols-3">
          <section className="card animate-fade-in p-6 lg:col-span-2 lg:self-start" style={{ animationDelay: "120ms" }}>
            <SectionHead label="Content overview" href="/library" />
            <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
              {METRICS.map((m) => {
                const body = (
                  <>
                    <div className="text-[26px] font-bold leading-none tracking-tight text-[var(--text)]">
                      {m.soon ? "—" : pad2(m.value)}
                    </div>
                    <div className="mt-2 flex items-center gap-2 text-[13px] text-[var(--text-2)]">
                      {m.label}
                      {m.soon && <BetaPill />}
                    </div>
                    <div className={`mt-3 h-0.5 w-8 rounded-full ${m.soon ? "bg-[var(--border-strong)]" : "bg-[var(--brand)]"}`} />
                  </>
                );
                return m.href && !m.soon ? (
                  <Link key={m.label} href={m.href} className="block rounded-lg transition-colors hover:text-[var(--brand)]">
                    {body}
                  </Link>
                ) : (
                  <div key={m.label}>{body}</div>
                );
              })}
            </div>

            {/* continue where you left off */}
            {resume && (
              <div className="mt-6 border-t border-[var(--border)] pt-5">
                <SectionHead label="Continue where you left off" />
                <Link
                  href={`/projects/${resume.project.id}`}
                  className="mt-3 flex items-center gap-4 rounded-lg border border-[var(--border)] p-3 transition-colors hover:border-[var(--brand)] hover:bg-[var(--brand-soft)]"
                >
                  <span className="relative flex h-14 w-24 flex-none items-center justify-center overflow-hidden rounded-md bg-[var(--navy)]">
                    {resume.session.poster ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={mediaUrl(resume.session.poster)} alt="" className="h-full w-full object-cover" />
                    ) : null}
                    <span className="absolute flex h-7 w-7 items-center justify-center rounded-full bg-white/90 pl-0.5 text-[var(--navy)]">
                      <IconPlay width={11} height={11} />
                    </span>
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[15px] font-semibold text-[var(--text)]">{resume.project.name}</span>
                    <span className="mt-0.5 block text-[13px] text-[var(--text-2)]">
                      Video ·{" "}
                      {STATUS_LABEL[resume.session.status] ?? resume.session.status}
                      {resume.session.duration_ms ? ` · ${mmss(resume.session.duration_ms)}` : ""} ·{" "}
                      {relTime(resume.session.created_at)}
                    </span>
                  </span>
                  <span className="btn btn-primary btn-sm flex-none">Continue</span>
                </Link>
              </div>
            )}
          </section>

          <section className="card animate-fade-in p-6" style={{ animationDelay: "160ms" }}>
            <SectionHead label="Recent activity" href="/library" />
            {activity.length === 0 ? (
              <p className="mt-4 text-[13px] text-[var(--text-3)]">
                {term ? "Nothing matches your search." : "Your first recording will show up here."}
              </p>
            ) : (
              <ul className="mt-3 divide-y divide-[var(--border)]">
                {activity.map((a) => (
                  <li key={a.key}>
                    <Link href={a.href} className="group flex items-start gap-3 py-2.5">
                      <span className="mt-[7px] h-1.5 w-1.5 flex-none rounded-full bg-[var(--brand)]" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] font-medium text-[var(--text)] group-hover:text-[var(--brand)]">
                          {a.title}
                        </span>
                        <span className="block text-[12.5px] text-[var(--text-3)]">
                          {a.kind} · Updated {relTime(a.at)}
                        </span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {/* ---- recent projects ---------------------------------------------- */}
        <section className="card animate-fade-in mt-5 p-6" style={{ animationDelay: "200ms" }}>
          <SectionHead label="Recent projects" href="/library" />
          {recentProjects.length === 0 ? (
            <div className="mt-4">
              <EmptyState
                icon={<IconFolder width={26} height={26} />}
                title={term ? "No projects match your search." : "No projects yet"}
                hint={term ? undefined : "Start a recording or upload a video to see it here."}
              />
            </div>
          ) : (
            <ul className="mt-3 divide-y divide-[var(--border)]">
              {recentProjects.slice(0, 6).map((p) => {
                const mine = byProject.get(p.id) ?? [];
                const latest = mine[0];
                const captures = p.capture_count ?? mine.length;
                const parts = [
                  `${captures} ${captures === 1 ? "video" : "videos"}`,
                  isDocProject(p) ? "1 document" : null,
                  `Updated ${relTime(latest?.created_at ?? p.created_at)}`,
                ].filter(Boolean);
                return (
                  <li key={p.id}>
                    <Link href={`/projects/${p.id}`} className="group flex items-center gap-4 py-3">
                      <span className="flex h-9 w-9 flex-none items-center justify-center rounded-lg bg-[var(--brand-soft)] text-[var(--brand)]">
                        {isDocProject(p) ? <IconDoc width={16} height={16} /> : <IconVideo width={16} height={16} />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[15px] font-semibold text-[var(--text)] group-hover:text-[var(--brand)]">
                          {p.name}
                          {p.shared_with_me && (
                            <span className="ml-2 align-middle text-[11px] font-medium text-[var(--text-3)]">Shared with you</span>
                          )}
                        </span>
                        <span className="block text-[12.5px] text-[var(--text-3)]">{parts.join(" · ")}</span>
                      </span>
                      <IconChevronRight width={16} height={16} className="flex-none text-[var(--text-3)] group-hover:text-[var(--brand)]" />
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* ---- knowledge hub ------------------------------------------------ */}
        <section
          className="animate-fade-in relative mt-5 overflow-hidden rounded-xl px-6 py-7 text-white md:px-8"
          style={{ animationDelay: "240ms", background: "linear-gradient(105deg, var(--navy) 0%, var(--navy-2) 55%, var(--brand) 140%)" }}
        >
          <div aria-hidden className="pointer-events-none absolute inset-y-0 right-0 w-1/2">
            <div className="absolute -right-10 -top-10 h-[240%] w-32 -rotate-[28deg] bg-white opacity-[0.05]" />
            <div className="absolute right-24 -top-10 h-[240%] w-14 -rotate-[28deg] bg-[var(--brand)] opacity-30" />
          </div>
          <div className="relative flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-white/60">Knowledge hub</span>
              <h2 className="mt-1.5 text-[20px] font-semibold tracking-tight">Everything your team knows, in one place.</h2>
              <div className="mt-4 flex flex-wrap gap-x-7 gap-y-2 text-[14px] text-white/80">
                <span><strong className="font-semibold text-white">{projects.length}</strong> projects</span>
                <span><strong className="font-semibold text-white">{sessions.length}</strong> videos</span>
                <span><strong className="font-semibold text-white">{documentsCount}</strong> documents</span>
              </div>
            </div>
            <Link href="/library" className="btn bg-white text-[var(--navy)] hover:bg-white/90">
              Explore library <IconArrowRight width={15} height={15} />
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
