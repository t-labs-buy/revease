"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { listArticles, listProjects, listSessions, mediaUrl, type Project, type Session } from "@/lib/api";
import { CaptureModal, type CaptureIntent } from "@/components/CaptureModal";
import { EmptyState } from "@/components/ui";
import {
  IconArrowRight,
  IconBell,
  IconBook,
  IconChevronDown,
  IconDatabase,
  IconDoc,
  IconFolder,
  IconLibrary,
  IconMoreHorizontal,
  IconPlay,
  IconPlus,
  IconSearch,
  IconSettings,
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
  const [kbCount, setKbCount] = useState(0);
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

  const isDocProject = (p: Project) => sessions.filter((s) => s.project_id === p.id).length > 1;

  const FEATURES = [
    {
      title: "Record your screen",
      desc: "Capture your screen and microphone. AI will handle the rest.",
      icon: <IconVideo width={26} height={26} />,
      cta: "Start recording",
      onClick: () => open("record"),
      accent: "#7C3AED",
      gradient: "linear-gradient(135deg, rgba(124,58,237,0.12), rgba(167,139,250,0.04))",
      border: "rgba(124,58,237,0.16)",
      art: (
        <div className="flex flex-col items-center gap-2">
          <span className="flex h-20 w-28 items-center justify-center rounded-2xl bg-white/70 shadow-sm ring-1 ring-black/5">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-[#7C3AED]/10 px-3 py-1.5 text-xs font-semibold text-[#7C3AED]">
              <span className="h-2 w-2 rounded-full bg-red-500" /> REC
            </span>
          </span>
        </div>
      ),
    },
    {
      title: "Create a video",
      desc: "Polished videos with AI voiceover, auto-zoom and captions.",
      icon: <IconSparkles width={26} height={26} />,
      cta: "Create video",
      onClick: () => open("video"),
      accent: "#EC4899",
      gradient: "linear-gradient(135deg, rgba(236,72,153,0.12), rgba(244,114,182,0.04))",
      border: "rgba(236,72,153,0.16)",
      art: (
        <div className="flex w-28 flex-col items-center gap-2 rounded-2xl bg-white/70 p-3.5 shadow-sm ring-1 ring-black/5">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-[#EC4899] pl-0.5 text-white shadow">
            <IconPlay width={18} height={18} />
          </span>
          <span className="relative h-1.5 w-full rounded-full bg-[#EC4899]/20">
            <span className="absolute left-0 top-0 h-full w-1/3 rounded-full bg-[#EC4899]" />
            <span className="absolute left-1/3 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#EC4899]" />
          </span>
        </div>
      ),
    },
    {
      title: "Create a document",
      desc: "Step-by-step guides & SOPs generated from your captures.",
      icon: <IconDoc width={26} height={26} />,
      cta: "Create document",
      onClick: () => open("doc"),
      accent: "#10B981",
      gradient: "linear-gradient(135deg, rgba(16,185,129,0.12), rgba(52,211,153,0.04))",
      border: "rgba(16,185,129,0.16)",
      art: (
        <div className="relative h-28 w-24 rounded-2xl bg-white/80 p-3.5 shadow-sm ring-1 ring-black/5">
          <span className="block h-1.5 w-3/4 rounded bg-[#10B981]/70" />
          <span className="mt-3 block h-1 w-full rounded bg-black/10" />
          <span className="mt-1.5 block h-1 w-5/6 rounded bg-black/10" />
          <span className="mt-1.5 block h-1 w-full rounded bg-black/10" />
          <span className="mt-1.5 block h-1 w-2/3 rounded bg-black/10" />
        </div>
      ),
    },
  ];

  const documentsCount = projects.filter(isDocProject).length;

  const STATS = [
    { label: "Projects", value: projects.length, icon: <IconFolder width={20} height={20} />, color: "#7C3AED" },
    { label: "Videos", value: sessions.length, icon: <IconVideo width={20} height={20} />, color: "#EC4899" },
    { label: "Documents", value: documentsCount, icon: <IconDoc width={20} height={20} />, color: "#10B981" },
    { label: "Knowledge Bases", value: kbCount, icon: <IconDatabase width={20} height={20} />, color: "#A78BFA" },
  ];

  const QUICK = [
    { title: "Record", desc: "Capture screen & voice", icon: <IconVideo width={22} height={22} />, onClick: () => open("record") },
    { title: "Upload", desc: "Bring an MP4 or MOV", icon: <IconUpload width={22} height={22} />, onClick: () => open("upload") },
    { title: "New video", desc: "AI video from a capture", icon: <IconSparkles width={22} height={22} />, onClick: () => open("video") },
    { title: "New doc", desc: "AI step-by-step guide", icon: <IconDoc width={22} height={22} />, onClick: () => open("doc") },
    { title: "Library", desc: "All your content", icon: <IconLibrary width={22} height={22} />, href: "/library" },
    { title: "Knowledge base", desc: "Team guides in one place", icon: <IconBook width={22} height={22} />, href: "/knowledge-base" },
  ];

  const NAV = [
    { label: "Home", href: "/", active: true },
    { label: "Library", href: "/library", active: false },
    { label: "Knowledge Base", href: "/knowledge-base", active: false },
  ];

  const filtered = projects.filter((p) => p.name.toLowerCase().includes(q.trim().toLowerCase()));

  return (
    <main className="min-h-screen bg-[var(--bg)]">
      {modal && <CaptureModal intent={modal} onClose={() => setModal(null)} />}

      {/* header */}
      <div className="sticky top-0 z-20 flex items-center gap-6 border-b border-[var(--border)] bg-[var(--bg)]/85 px-8 py-3 backdrop-blur-md">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-[#7C3AED] to-[#A78BFA] text-base font-bold text-white shadow-sm shadow-[#7C3AED]/30">
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
              className={`rounded-full px-4 py-2 text-sm font-medium transition-colors duration-200 ${
                n.active
                  ? "bg-[#7C3AED]/10 text-[#7C3AED]"
                  : "text-[var(--text-2)] hover:bg-[var(--hover)] hover:text-[var(--text)]"
              }`}
            >
              {n.label}
            </Link>
          ))}
        </nav>

        <div className="relative ml-auto w-full max-w-xl">
          <IconSearch
            width={16}
            height={16}
            className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-[var(--text-3)]"
          />
          <input
            ref={searchRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search projects, videos, documents..."
            className="input input-pill py-2.5 pl-10 pr-14"
          />
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 rounded-md border border-[var(--border)] bg-[var(--hover)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--text-3)]">
            ⌘K
          </span>
        </div>
        <div className="flex items-center gap-2.5">
          <button className="relative flex h-10 w-10 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--card)] text-[var(--text-2)] transition-colors hover:text-[var(--text)]">
            <IconBell width={17} height={17} />
            <span className="absolute right-2.5 top-2 h-1.5 w-1.5 rounded-full bg-[#EC4899]" />
          </button>
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-[#7C3AED] to-[#A78BFA] text-sm font-semibold text-white">
            U
          </span>
        </div>
      </div>

      <div className="mx-auto max-w-[1600px] px-8 py-10">
        {/* greeting */}
        <section className="animate-fade-in">
          <h1 className="text-[42px] font-bold leading-[1.1] tracking-tight text-[var(--text)]">
            {greeting}, User <span className="align-middle">👋</span>
          </h1>
          <p className="mt-2.5 text-lg text-[var(--text-2)]">
            Create tutorials, videos and documentation using AI.
          </p>
        </section>

        {error && (
          <p className="mt-6 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
            {error}
          </p>
        )}

        {/* feature cards */}
        <div className="mt-12 grid gap-6 md:grid-cols-3">
          {FEATURES.map((f, i) => (
            <div
              key={f.title}
              className="animate-fade-in group relative flex min-h-[240px] flex-col overflow-hidden rounded-[20px] border p-7 shadow-[var(--shadow-card)] transition-all duration-[250ms] ease-out hover:-translate-y-1 hover:shadow-[var(--shadow-card-hover)]"
              style={{ background: f.gradient, borderColor: f.border, animationDelay: `${i * 60}ms` }}
            >
              <span
                className="flex h-14 w-14 items-center justify-center rounded-2xl shadow-sm"
                style={{ backgroundColor: `${f.accent}1f`, color: f.accent }}
              >
                {f.icon}
              </span>
              <h3 className="mt-5 text-[22px] font-semibold text-[var(--text)]">{f.title}</h3>
              <p className="mt-2 max-w-[75%] text-[15px] leading-relaxed text-[var(--text-2)]">{f.desc}</p>
              <button
                onClick={f.onClick}
                className="mt-6 inline-flex w-fit items-center gap-1.5 rounded-xl px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition-transform duration-200 hover:scale-[1.03]"
                style={{ backgroundColor: f.accent }}
              >
                {f.cta} <IconArrowRight width={15} height={15} />
              </button>
              {/* decorative art */}
              <div className="pointer-events-none absolute -right-2 bottom-4 opacity-90 transition-transform duration-[250ms] group-hover:scale-105">
                {f.art}
              </div>
            </div>
          ))}
        </div>

        {/* stats */}
        <div className="mt-12 grid grid-cols-2 gap-6 sm:grid-cols-4">
          {STATS.map((s) => (
            <div key={s.label} className="card flex items-center gap-4 p-5">
              <span
                className="flex h-12 w-12 flex-none items-center justify-center rounded-2xl"
                style={{ backgroundColor: `${s.color}1a`, color: s.color }}
              >
                {s.icon}
              </span>
              <div className="min-w-0">
                <div className="text-2xl font-bold text-[var(--text)]">{s.value}</div>
                <div className="truncate text-sm text-[var(--text-2)]">{s.label}</div>
              </div>
            </div>
          ))}
        </div>

        {/* quick access */}
        <div className="mt-12 flex items-center justify-between">
          <h2 className="text-[28px] font-semibold tracking-tight text-[var(--text)]">Quick access</h2>
          <button
            title="Coming soon"
            className="inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium text-[#7C3AED] opacity-90 transition-colors hover:bg-[#7C3AED]/10"
          >
            <IconSettings width={15} height={15} /> Customize
          </button>
        </div>
        <div className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-3 lg:grid-cols-6">
          {QUICK.map((t) => {
            const inner = (
              <div className="card card-hover flex h-full flex-col items-start gap-3 p-5 text-left">
                <span className="flex h-12 w-12 flex-none items-center justify-center rounded-2xl bg-[#7C3AED]/10 text-[#7C3AED]">
                  {t.icon}
                </span>
                <div className="min-w-0">
                  <div className="text-[15px] font-semibold text-[var(--text)]">{t.title}</div>
                  <div className="mt-0.5 text-sm leading-snug text-[var(--text-2)]">{t.desc}</div>
                </div>
              </div>
            );
            return t.href ? (
              <Link key={t.title} href={t.href} className="block h-full">
                {inner}
              </Link>
            ) : (
              <button key={t.title} onClick={t.onClick} className="block h-full text-left">
                {inner}
              </button>
            );
          })}
        </div>

        {/* recent projects */}
        <div className="mt-12 flex items-center justify-between">
          <h2 className="text-[28px] font-semibold tracking-tight text-[var(--text)]">Recent projects</h2>
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--card)] px-3.5 py-1.5 text-sm text-[var(--text-2)] shadow-[var(--shadow-card)]">
              All projects <IconChevronDown width={14} height={14} className="text-[var(--text-3)]" />
            </span>
            <Link href="/library" className="inline-flex items-center gap-1 text-sm font-medium text-[#7C3AED]">
              View all <IconArrowRight width={14} height={14} />
            </Link>
          </div>
        </div>

        {filtered.length === 0 ? (
          <div className="mt-6">
            <EmptyState
              icon={<IconLibrary width={28} height={28} />}
              title={q ? "No projects match your search." : "No projects yet"}
              hint={q ? undefined : "Start a recording or upload a video to see it here."}
            />
          </div>
        ) : (
          <div className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {filtered.map((p, i) => {
              const mine = sessions.filter((s) => s.project_id === p.id);
              const latest = [...mine].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
              const isDoc = mine.length > 1;
              return (
                <Link key={p.id} href={`/projects/${p.id}`} className="card card-hover group flex flex-col overflow-hidden">
                  {/* thumbnail */}
                  <div className="relative aspect-video overflow-hidden bg-gradient-to-br from-[#1c1c2e] to-[#2b2b45]">
                    {latest?.poster ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={mediaUrl(latest.poster)} alt={p.name} className="h-full w-full object-cover" />
                    ) : (
                      <div className={`h-full w-full bg-gradient-to-br ${GRADS[i % GRADS.length]} opacity-70`} />
                    )}
                    <span className="absolute inset-0 flex items-center justify-center">
                      <span className="flex h-11 w-11 items-center justify-center rounded-full bg-white/90 pl-0.5 text-[#7C3AED] shadow-lg">
                        <IconPlay width={16} height={16} />
                      </span>
                    </span>
                    {latest?.duration_ms ? (
                      <span className="absolute bottom-2 right-2 rounded-md bg-black/70 px-1.5 py-0.5 text-[11px] font-medium text-white">
                        {mmss(latest.duration_ms)}
                      </span>
                    ) : null}
                  </div>

                  {/* body */}
                  <div className="flex flex-1 flex-col p-5">
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="truncate text-[17px] font-semibold text-[var(--text)]">{p.name}</h3>
                      <button
                        title="More"
                        onClick={(e) => e.preventDefault()}
                        className="flex-none rounded-lg p-1 text-[var(--text-3)] opacity-0 transition-opacity hover:text-[var(--text)] group-hover:opacity-100"
                      >
                        <IconMoreHorizontal width={18} height={18} />
                      </button>
                    </div>
                    <div className="mt-1 text-sm text-[var(--text-2)]">
                      {new Date(p.created_at).toLocaleDateString(undefined, {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                      })}
                    </div>
                    <div className="mt-3.5 flex items-center justify-between border-t border-[var(--border)] pt-3">
                      <span
                        className={`badge px-2.5 py-1 ${
                          isDoc ? "bg-emerald-500/10 text-emerald-500" : "bg-[#7C3AED]/10 text-[#7C3AED]"
                        }`}
                      >
                        {isDoc ? "Document" : "Video"}
                      </span>
                      <span className="text-xs text-[var(--text-3)]">{relTime(latest?.created_at ?? p.created_at)}</span>
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>

      {/* floating create button */}
      <div className="group fixed bottom-6 right-6 z-40">
        <span
          aria-hidden
          className="absolute inset-0 rounded-full bg-gradient-to-br from-[#7C3AED] to-[#8B5CF6] opacity-40 blur-xl transition-opacity duration-[250ms] group-hover:opacity-70"
        />
        <button
          onClick={() => open("video")}
          title="Create new"
          className="relative inline-flex items-center gap-2 rounded-full bg-gradient-to-br from-[#7C3AED] to-[#8B5CF6] py-4 pl-5 pr-6 text-sm font-semibold text-white shadow-[0_8px_24px_-4px_rgba(124,58,237,0.5)] transition-transform duration-[250ms] hover:scale-105"
        >
          <IconPlus width={18} height={18} /> New project
        </button>
      </div>
    </main>
  );
}
