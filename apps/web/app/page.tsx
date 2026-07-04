"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { listProjects, listSessions, type Project, type Session } from "@/lib/api";
import { ProjectCard } from "@/components/ProjectCard";
import { CaptureModal, type CaptureIntent } from "@/components/CaptureModal";
import {
  IconBook,
  IconDoc,
  IconLibrary,
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

const GRADS = [
  "from-[#6d5dfb] to-[#a855f7]",
  "from-[#8b5cf6] to-[#ec4899]",
  "from-[#6366f1] to-[#06b6d4]",
  "from-[#f97316] to-[#ec4899]",
];

export default function Home() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<CaptureIntent | null>(null);
  const [greeting, setGreeting] = useState("Welcome");
  const [q, setQ] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const rowRef = useRef<HTMLDivElement>(null);

  useEffect(() => setGreeting(timeGreeting()), []);
  useEffect(() => {
    Promise.all([listSessions(), listProjects()])
      .then(([s, ps]) => {
        setSessions(s);
        setProjects(ps.slice(0, 12));
      })
      .catch((e) => setError(String(e)));
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

  const FEATURES = [
    {
      title: "Record your screen",
      desc: "Capture your workflow and let AI turn it into everything.",
      icon: <IconVideo width={20} height={20} />,
      cta: "Start recording",
      onClick: () => open("record"),
      grad: "from-[#6d5dfb] via-[#7c5cf6] to-[#a855f7]",
      art: (
        <div className="flex flex-col items-center gap-2">
          <span className="flex h-20 w-20 items-center justify-center rounded-2xl bg-white/15">
            <span className="flex h-12 w-12 items-center justify-center rounded-full border-2 border-white/70">
              <span className="h-4 w-4 rounded-full bg-red-400" />
            </span>
          </span>
          <span className="flex h-8 items-end gap-[3px] rounded-lg bg-white/15 px-2 py-1.5">
            {Array.from({ length: 14 }).map((_, i) => (
              <span key={i} className="w-[3px] rounded bg-white/80" style={{ height: `${25 + Math.abs(Math.sin(i * 1.9)) * 75}%` }} />
            ))}
          </span>
        </div>
      ),
    },
    {
      title: "Create a Video",
      desc: "Polished product videos with AI voiceover and auto-zoom.",
      icon: <IconSparkles width={20} height={20} />,
      cta: "Create video",
      onClick: () => open("video"),
      grad: "from-[#8b5cf6] via-[#c05cf1] to-[#ec83d8]",
      art: (
        <div className="flex w-24 flex-col items-center gap-2 rounded-2xl bg-white/15 p-3">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-white/90 text-[#8b5cf6]">▶</span>
          <span className="relative h-1.5 w-full rounded-full bg-white/30">
            <span className="absolute left-0 top-0 h-full w-1/3 rounded-full bg-white/90" />
            <span className="absolute left-1/3 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white" />
          </span>
        </div>
      ),
    },
    {
      title: "Create a Document",
      desc: "Step-by-step guides & SOPs generated from the same capture.",
      icon: <IconDoc width={20} height={20} />,
      cta: "Create doc",
      onClick: () => open("doc"),
      grad: "from-[#6366f1] via-[#8b5cf6] to-[#3b82f6]",
      art: (
        <div className="relative h-24 w-20 rounded-xl bg-white/90 p-3 shadow-lg">
          <span className="absolute -right-1 -top-1 h-6 w-6 rounded-bl-xl rounded-tr-xl bg-white/60" />
          <span className="block h-1.5 w-3/4 rounded bg-[#8b5cf6]/70" />
          <span className="mt-2 block h-1 w-full rounded bg-[#c7c9d6]" />
          <span className="mt-1.5 block h-1 w-5/6 rounded bg-[#c7c9d6]" />
          <span className="mt-1.5 block h-1 w-full rounded bg-[#c7c9d6]" />
          <span className="mt-1.5 block h-1 w-2/3 rounded bg-[#c7c9d6]" />
        </div>
      ),
    },
  ];

  const QUICK = [
    { title: "Record", desc: "Capture screen & voice", icon: <IconVideo />, onClick: () => open("record") },
    { title: "Upload", desc: "Bring an MP4 or MOV", icon: <IconUpload />, onClick: () => open("upload") },
    { title: "New Video", desc: "AI video from a capture", icon: <IconSparkles />, onClick: () => open("video") },
    { title: "New Doc", desc: "AI step-by-step guide", icon: <IconDoc />, onClick: () => open("doc") },
    { title: "Library", desc: "All your content", icon: <IconLibrary />, href: "/library" },
    { title: "Knowledge Base", desc: "Team guides in one place", icon: <IconBook />, href: "/knowledge-base" },
  ];

  const filtered = projects.filter((p) => p.name.toLowerCase().includes(q.trim().toLowerCase()));

  return (
    <main className="min-h-screen">
      {modal && <CaptureModal intent={modal} onClose={() => setModal(null)} />}

      {/* header */}
      <div className="sticky top-0 z-20 flex items-center gap-6 border-b border-[var(--border)] bg-[var(--bg)]/85 px-8 py-3 backdrop-blur-md">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-[#6d5dfb] to-[#a855f7] text-base font-bold text-white shadow-sm shadow-[#6d5dfb]/30">
            R
          </span>
          <span className="text-[17px] font-semibold tracking-tight text-[var(--text)]">RevEase</span>
        </Link>
        <div className="relative ml-auto w-full max-w-md">
          <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-3)]">⌕</span>
          <input
            ref={searchRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search anything…"
            className="input rounded-full pl-9 pr-14"
          />
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 rounded-md border border-[var(--border)] bg-[var(--hover)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--text-3)]">
            ⌘K
          </span>
        </div>
        <div className="flex items-center gap-2.5">
          <button className="relative flex h-10 w-10 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--card)] text-[var(--text-2)] hover:text-[var(--text)]">
            🔔
            <span className="absolute right-2.5 top-2 h-1.5 w-1.5 rounded-full bg-[#ec4899]" />
          </button>
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-[#6d5dfb] to-[#a855f7] text-sm font-semibold text-white">
            U
          </span>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-8 py-8">
        {/* hero */}
        <h1 className="text-4xl font-semibold tracking-tight text-[var(--text)]">
          {greeting}, User <span className="align-middle">👋</span>
        </h1>
        <p className="mt-1.5 text-[15px] text-[var(--text-2)]">Ready to create something amazing today?</p>

        {error && (
          <p className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
            {error}
          </p>
        )}

        {/* feature cards */}
        <div className="mt-8 grid gap-5 md:grid-cols-3">
          {FEATURES.map((f) => (
            <div
              key={f.title}
              className={`relative flex min-h-[220px] flex-col overflow-hidden rounded-2xl bg-gradient-to-br ${f.grad} p-6`}
            >
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/20 text-white backdrop-blur-sm">
                {f.icon}
              </span>
              <h3 className="mt-4 text-xl font-semibold text-white">{f.title}</h3>
              <p className="mt-1.5 max-w-[65%] text-sm leading-snug text-white/85">{f.desc}</p>
              <button
                onClick={f.onClick}
                className="mt-auto inline-flex items-center gap-1.5 self-start rounded-xl bg-white/20 px-4 py-2 text-sm font-semibold text-white backdrop-blur-sm transition-colors hover:bg-white/30"
              >
                {f.cta} <span aria-hidden>→</span>
              </button>
              {/* decorative art */}
              <div className="pointer-events-none absolute -right-2 top-1/2 -translate-y-1/2 pr-5 opacity-95">{f.art}</div>
              <div className="pointer-events-none absolute -right-10 -top-10 h-36 w-36 rounded-full bg-white/10 blur-2xl" />
            </div>
          ))}
        </div>

        {/* quick tools */}
        <div className="mt-12 flex items-center justify-between">
          <h2 className="text-lg font-semibold tracking-tight text-[var(--text)]">Quick Tools</h2>
          <button title="Coming soon" className="inline-flex items-center gap-1.5 text-sm font-medium text-[var(--brand-2)] opacity-80">
            Customize ⚙
          </button>
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          {QUICK.map((t) => {
            const inner = (
              <div className="card card-hover flex h-full items-start gap-3 p-4 text-left">
                <span className="flex h-10 w-10 flex-none items-center justify-center rounded-xl bg-[#6d5dfb]/12 text-[var(--brand-2)]">
                  {t.icon}
                </span>
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-[var(--text)]">{t.title}</div>
                  <div className="mt-0.5 text-xs leading-snug text-[var(--text-2)]">{t.desc}</div>
                </div>
              </div>
            );
            return t.href ? (
              <Link key={t.title} href={t.href}>
                {inner}
              </Link>
            ) : (
              <button key={t.title} onClick={t.onClick} className="text-left">
                {inner}
              </button>
            );
          })}
        </div>

        {/* recent projects */}
        <div className="mt-12 flex items-center justify-between">
          <h2 className="text-lg font-semibold tracking-tight text-[var(--text)]">Recent Projects</h2>
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--card)] px-3.5 py-1.5 text-sm text-[var(--text-2)]">
              All projects <span className="text-[var(--text-3)]">▾</span>
            </span>
            <Link href="/library" className="inline-flex items-center gap-1 text-sm font-medium text-[var(--brand-2)]">
              View all <span aria-hidden>→</span>
            </Link>
          </div>
        </div>

        {filtered.length === 0 ? (
          <p className="mt-4 text-sm text-[var(--text-2)]">
            {q ? "No projects match your search." : "No projects yet — start a recording or upload a video to see it here."}
          </p>
        ) : (
          <div className="relative mt-4">
            <div ref={rowRef} className="flex gap-4 overflow-x-auto scroll-smooth pb-2 [scrollbar-width:none]">
              {filtered.map((p, i) => (
                <ProjectCard key={p.id} project={p} sessions={sessions} index={i} className="w-[280px] flex-none" />
              ))}
            </div>
            {filtered.length > 4 && (
              <button
                onClick={() => rowRef.current?.scrollBy({ left: 600, behavior: "smooth" })}
                className="absolute -right-4 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--card)] text-[var(--text-2)] shadow-xl hover:text-[var(--text)]"
                title="Scroll"
              >
                ›
              </button>
            )}
          </div>
        )}
      </div>

      {/* floating create button */}
      <button
        onClick={() => open("video")}
        title="Create new"
        className="fixed bottom-6 right-6 z-40 flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-[#6d5dfb] to-[#8b5cf6] text-2xl text-white shadow-xl shadow-[#6d5dfb]/40 transition-transform hover:scale-105"
      >
        +
      </button>
    </main>
  );
}
