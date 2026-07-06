"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { listProjects, listSessions, mediaUrl, type Project, type Session } from "@/lib/api";
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

const mmss = (ms: number) =>
  `${String(Math.floor(ms / 60000)).padStart(2, "0")}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, "0")}`;

const relTime = (iso?: string) => {
  if (!iso) return "recently";
  const d = new Date(iso).getTime();
  if (isNaN(d)) return "recently";
  const s = Math.max(1, Math.floor((Date.now() - d) / 1000));
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `Updated ${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `Updated ${h}h ago`;
  const day = Math.floor(h / 24);
  if (day < 30) return `Updated ${day}d ago`;
  return `Updated ${Math.floor(day / 30)}mo ago`;
};

export default function Home() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState<CaptureIntent | null>(null);
  const [greeting, setGreeting] = useState("Welcome");
  const [q, setQ] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

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
      desc: "Capture your screen and microphone. AI will handle the rest.",
      icon: <IconVideo width={20} height={20} />,
      cta: "Start recording",
      onClick: () => open("record"),
      accent: "#6d5dfb",
      art: (
        <div className="flex flex-col items-center gap-2">
          <span className="flex h-16 w-24 items-center justify-center rounded-xl bg-white/70 shadow-sm ring-1 ring-black/5">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[#6d5dfb]/10 px-2.5 py-1 text-[11px] font-semibold text-[#6d5dfb]">
              <span className="h-2 w-2 rounded-full bg-red-500" /> REC
            </span>
          </span>
        </div>
      ),
    },
    {
      title: "Create a video",
      desc: "Polished videos with AI voiceover, auto-zoom and captions.",
      icon: <IconSparkles width={20} height={20} />,
      cta: "Create video",
      onClick: () => open("video"),
      accent: "#ec4899",
      art: (
        <div className="flex w-24 flex-col items-center gap-2 rounded-xl bg-white/70 p-3 shadow-sm ring-1 ring-black/5">
          <span className="flex h-11 w-11 items-center justify-center rounded-full bg-[#ec4899] pl-0.5 text-white shadow">
            ▶
          </span>
          <span className="relative h-1.5 w-full rounded-full bg-[#ec4899]/20">
            <span className="absolute left-0 top-0 h-full w-1/3 rounded-full bg-[#ec4899]" />
            <span className="absolute left-1/3 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#ec4899]" />
          </span>
        </div>
      ),
    },
    {
      title: "Create a document",
      desc: "Step-by-step guides & SOPs generated from your captures.",
      icon: <IconDoc width={20} height={20} />,
      cta: "Create document",
      onClick: () => open("doc"),
      accent: "#10b981",
      art: (
        <div className="relative h-24 w-20 rounded-xl bg-white/80 p-3 shadow-sm ring-1 ring-black/5">
          <span className="block h-1.5 w-3/4 rounded bg-[#10b981]/70" />
          <span className="mt-2.5 block h-1 w-full rounded bg-black/10" />
          <span className="mt-1.5 block h-1 w-5/6 rounded bg-black/10" />
          <span className="mt-1.5 block h-1 w-full rounded bg-black/10" />
          <span className="mt-1.5 block h-1 w-2/3 rounded bg-black/10" />
        </div>
      ),
    },
  ];

  const QUICK = [
    { title: "Record", desc: "Capture screen & voice", icon: <IconVideo />, onClick: () => open("record") },
    { title: "Upload", desc: "Bring an MP4 or MOV", icon: <IconUpload />, onClick: () => open("upload") },
    { title: "New video", desc: "AI video from a capture", icon: <IconSparkles />, onClick: () => open("video") },
    { title: "New doc", desc: "AI step-by-step guide", icon: <IconDoc />, onClick: () => open("doc") },
    { title: "Library", desc: "All your content", icon: <IconLibrary />, href: "/library" },
    { title: "Knowledge base", desc: "Team guides in one place", icon: <IconBook />, href: "/knowledge-base" },
  ];

  const NAV = [
    { label: "Home", href: "/", active: true },
    { label: "Library", href: "/library", active: false },
    { label: "Knowledge Base", href: "/knowledge-base", active: false },
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

        {/* center nav */}
        <nav className="hidden items-center gap-1 md:flex">
          {NAV.map((n) => (
            <Link
              key={n.label}
              href={n.href}
              className={`relative rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                n.active
                  ? "text-[var(--brand-2)]"
                  : "text-[var(--text-2)] hover:text-[var(--text)]"
              }`}
            >
              {n.label}
              {n.active && (
                <span className="absolute inset-x-3 -bottom-[13px] h-0.5 rounded-full bg-[var(--brand-2)]" />
              )}
            </Link>
          ))}
        </nav>

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
        <p className="mt-1.5 text-[15px] text-[var(--text-2)]">What would you like to create today?</p>

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
              className="relative flex min-h-[210px] flex-col overflow-hidden rounded-2xl border p-6"
              style={{ backgroundColor: `${f.accent}0f`, borderColor: `${f.accent}26` }}
            >
              <span
                className="flex h-11 w-11 items-center justify-center rounded-xl"
                style={{ backgroundColor: `${f.accent}1f`, color: f.accent }}
              >
                {f.icon}
              </span>
              <h3 className="mt-4 text-xl font-semibold text-[var(--text)]">{f.title}</h3>
              <p className="mt-1.5 max-w-[62%] text-sm leading-snug text-[var(--text-2)]">{f.desc}</p>
              <button
                onClick={f.onClick}
                className="mt-auto inline-flex items-center gap-1.5 self-start text-sm font-semibold transition-opacity hover:opacity-80"
                style={{ color: f.accent }}
              >
                {f.cta} <span aria-hidden>→</span>
              </button>
              {/* decorative art */}
              <div className="pointer-events-none absolute right-5 top-1/2 -translate-y-1/2">{f.art}</div>
            </div>
          ))}
        </div>

        {/* quick access */}
        <div className="mt-12 flex items-center justify-between">
          <h2 className="text-lg font-semibold tracking-tight text-[var(--text)]">Quick access</h2>
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
          <h2 className="text-lg font-semibold tracking-tight text-[var(--text)]">Recent projects</h2>
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
          <div className="card mt-4 divide-y divide-[var(--border)] overflow-hidden">
            {filtered.map((p, i) => {
              const mine = sessions.filter((s) => s.project_id === p.id);
              const latest = [...mine].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
              const isDoc = mine.length > 1;
              return (
                <Link
                  key={p.id}
                  href={`/projects/${p.id}`}
                  className="group flex items-center gap-4 px-4 py-3.5 transition-colors hover:bg-[var(--card-hover)]"
                >
                  {/* thumbnail */}
                  <div className="relative h-[52px] w-[92px] flex-none overflow-hidden rounded-lg bg-gradient-to-br from-[#1c1c2e] to-[#2b2b45]">
                    {latest?.poster ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={mediaUrl(latest.poster)} alt={p.name} className="h-full w-full object-cover" />
                    ) : (
                      <div className={`h-full w-full bg-gradient-to-br ${GRADS[i % GRADS.length]} opacity-70`} />
                    )}
                    <span className="absolute inset-0 flex items-center justify-center">
                      <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white/90 pl-0.5 text-[11px] text-[#6d5dfb] shadow">
                        ▶
                      </span>
                    </span>
                    {latest?.duration_ms ? (
                      <span className="absolute bottom-1 right-1 rounded bg-black/70 px-1 py-0.5 text-[9px] font-medium text-white">
                        {mmss(latest.duration_ms)}
                      </span>
                    ) : null}
                  </div>

                  {/* title + meta */}
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-semibold text-[var(--text)]">{p.name}</div>
                    <div className="mt-0.5 text-xs text-[var(--text-2)]">
                      {mine.length} capture{mine.length === 1 ? "" : "s"} •{" "}
                      {new Date(p.created_at).toLocaleDateString(undefined, {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                      })}
                    </div>
                  </div>

                  {/* tag */}
                  <span
                    className={`hidden rounded-md px-2 py-1 text-xs font-medium sm:inline-flex ${
                      isDoc
                        ? "bg-emerald-500/10 text-emerald-500"
                        : "bg-[#6d5dfb]/10 text-[var(--brand-2)]"
                    }`}
                  >
                    {isDoc ? "Document" : "Video"}
                  </span>

                  {/* updated */}
                  <span className="hidden w-32 text-right text-xs text-[var(--text-3)] md:block">
                    {relTime(latest?.created_at ?? p.created_at)}
                  </span>

                  {/* menu */}
                  <button
                    title="More"
                    onClick={(e) => e.preventDefault()}
                    className="flex-none rounded-lg px-1.5 text-[var(--text-3)] opacity-0 transition-opacity hover:text-[var(--text)] group-hover:opacity-100"
                  >
                    ⋯
                  </button>
                </Link>
              );
            })}
          </div>
        )}
      </div>

      {/* floating create button */}
      <button
        onClick={() => open("video")}
        title="Create new"
        className="fixed bottom-6 right-6 z-40 inline-flex items-center gap-2 rounded-full bg-gradient-to-br from-[#6d5dfb] to-[#8b5cf6] py-3.5 pl-4 pr-5 text-sm font-semibold text-white shadow-xl shadow-[#6d5dfb]/40 transition-transform hover:scale-105"
      >
        <span className="text-lg leading-none">+</span> New project
      </button>
    </main>
  );
}
