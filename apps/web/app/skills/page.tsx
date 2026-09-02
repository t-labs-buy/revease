"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createSkill, deleteSkill, generateSkill, listSkills, type ListScope, type Skill } from "@/lib/api";
import { markdownToSkill } from "@/lib/skillmd";
import { Spinner } from "@/components/ui";
import { ScopeToggle } from "@/components/ScopeToggle";

/* One-click starting points (like installing a ready-made skill). */
const TEMPLATES: {
  name: string;
  target: "video" | "doc";
  icon: string;
  grad: string;
  desc: string;
  settings: Record<string, unknown>;
}[] = [
  {
    name: "Product Demo",
    target: "video",
    icon: "🎬",
    grad: "from-[#6d5dfb] to-[#a855f7]",
    desc: "Screen walkthrough with auto-zoom on clicks and a clear AI voiceover.",
    settings: {
      voice_id: "af_sarah",
      speed: 1,
      captions: true,
      motion_zoom: true,
      instruction:
        "Rewrite as a clear, confident product demo narration: explain what each screen and action does and why it matters, in a friendly professional tone.",
    },
  },
  {
    name: "Marketing Explainer",
    target: "video",
    icon: "✨",
    grad: "from-[#f97316] to-[#ec4899]",
    desc: "Punchy, benefit-led promo that hooks the viewer and ends with a CTA.",
    settings: {
      voice_id: "af_bella",
      speed: 1.05,
      captions: true,
      motion_zoom: true,
      instruction:
        "Rewrite as a punchy marketing explainer: benefit-led, exciting, hook early and end with a call to action.",
    },
  },
  {
    name: "SOP Document",
    target: "doc",
    icon: "📋",
    grad: "from-[#6366f1] to-[#06b6d4]",
    desc: "Formal Standard Operating Procedure with numbered, imperative steps.",
    settings: {
      instruction:
        "Rewrite as a formal Standard Operating Procedure: precise, imperative step titles and clear professional instructions.",
      sections: [
        { title: "Overview", description: "Summarize the purpose of this procedure.", include_screenshots: false },
        { title: "Steps", description: "List each step precisely, in order.", include_screenshots: true },
      ],
    },
  },
  {
    name: "FAQ Guide",
    target: "doc",
    icon: "❓",
    grad: "from-[#8b5cf6] to-[#ec4899]",
    desc: "Question-and-answer format generated from the transcript.",
    settings: {
      instruction:
        "Rewrite each step as a FAQ entry: phrase the title as a natural question and the body as a clear direct answer.",
    },
  },
];

function caps(s: Skill): string[] {
  const st = s.settings || {};
  const out: string[] = [];
  if (typeof st.voice_id === "string") out.push(`🎙 ${st.voice_id}`);
  if (st.captions === true) out.push("CC");
  if (st.motion_zoom === true) out.push("⛶ auto-zoom");
  const secs = Array.isArray(st.sections) ? (st.sections as unknown[]).length : 0;
  if (secs) out.push(`${secs} sections`);
  const tags = Array.isArray(st.tags) ? (st.tags as string[]) : [];
  return [...out, ...tags].slice(0, 4);
}

export default function SkillsPage() {
  const router = useRouter();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [scope, setScope] = useState<ListScope>("mine");

  const [aiOpen, setAiOpen] = useState(false);
  const [aiPrompt, setAiPrompt] = useState("");
  const [aiTarget, setAiTarget] = useState<"video" | "doc">("doc");
  const importRef = useRef<HTMLInputElement>(null);

  async function importFile(file: File) {
    setBusy("import");
    try {
      const md = await file.text();
      const parsed = markdownToSkill(md);
      const s = await createSkill(parsed);
      router.push(`/skills/${s.id}`);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setBusy(null);
    }
  }

  const load = () => listSkills(scope).then(setSkills).catch((e) => setError(String(e)));
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope]);

  async function fromTemplate(t: (typeof TEMPLATES)[number]) {
    setBusy(t.name);
    try {
      const s = await createSkill({ name: t.name, description: t.desc, target: t.target, settings: t.settings });
      router.push(`/skills/${s.id}`);
    } catch (e) {
      setError(String(e));
      setBusy(null);
    }
  }

  async function blank() {
    setBusy("blank");
    try {
      const s = await createSkill({ name: "Untitled skill", description: "", target: "doc", settings: {} });
      router.push(`/skills/${s.id}`);
    } catch (e) {
      setError(String(e));
      setBusy(null);
    }
  }

  async function buildWithAI() {
    if (!aiPrompt.trim() || busy) return;
    setBusy("ai");
    setError(null);
    try {
      const s = await generateSkill(aiPrompt, aiTarget);
      router.push(`/skills/${s.id}`);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setBusy(null);
    }
  }

  const video = skills.filter((s) => s.target === "video");
  const doc = skills.filter((s) => s.target === "doc");

  return (
    <main className="mx-auto max-w-5xl px-8 py-10">
      {/* hero */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-[var(--text)]">Skills</h1>
          <p className="mt-1.5 max-w-2xl text-[15px] text-[var(--text-2)]">
            Reusable AI capabilities that shape how RevEase generates a video or document — voice,
            tone, sections, formatting and branding. Pick a skill when you generate, and it does the
            rest.
          </p>
        </div>
        <ScopeToggle scope={scope} onChange={setScope} mineLabel="My skills" allLabel="All skills" />
        <button
          onClick={() => importRef.current?.click()}
          disabled={busy === "import"}
          className="btn btn-secondary whitespace-nowrap"
          title="Import a SKILL.md file"
        >
          {busy === "import" ? <Spinner /> : "⬆ Import"}
        </button>
        <input
          ref={importRef}
          type="file"
          accept=".md,.markdown,text/markdown,application/json"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) importFile(file);
            e.target.value = "";
          }}
        />
      </div>

      {error && (
        <p className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </p>
      )}

      {/* add a skill — 3 ways */}
      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <button
          onClick={() => setAiOpen((v) => !v)}
          className={`card card-hover flex items-start gap-3 p-4 text-left ${aiOpen ? "ring-1 ring-[#6d5dfb]" : ""}`}
        >
          <span className="flex h-10 w-10 flex-none items-center justify-center rounded-xl bg-gradient-to-br from-[#6d5dfb] to-[#a855f7] text-white">
            ✨
          </span>
          <div>
            <div className="text-sm font-semibold text-[var(--text)]">Build with AI</div>
            <div className="mt-0.5 text-xs text-[var(--text-2)]">Describe it — AI writes the skill.</div>
          </div>
        </button>
        <button onClick={blank} disabled={busy === "blank"} className="card card-hover flex items-start gap-3 p-4 text-left">
          <span className="flex h-10 w-10 flex-none items-center justify-center rounded-xl bg-[#6d5dfb]/12 text-[var(--brand-2)]">
            {busy === "blank" ? <Spinner /> : "✎"}
          </span>
          <div>
            <div className="text-sm font-semibold text-[var(--text)]">Write your own</div>
            <div className="mt-0.5 text-xs text-[var(--text-2)]">Start from a blank skill.</div>
          </div>
        </button>
        <Link href="/skills/gallery" className="card card-hover flex items-start gap-3 p-4 text-left">
          <span className="flex h-10 w-10 flex-none items-center justify-center rounded-xl bg-[#6d5dfb]/12 text-[var(--brand-2)]">
            📦
          </span>
          <div>
            <div className="text-sm font-semibold text-[var(--text)]">Browse the gallery</div>
            <div className="mt-0.5 text-xs text-[var(--text-2)]">Install a ready-made skill.</div>
          </div>
        </Link>
      </div>

      {/* AI panel */}
      {aiOpen && (
        <div className="card mt-4 space-y-3 p-5">
          <div className="flex gap-2">
            {(["doc", "video"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setAiTarget(t)}
                className={`btn btn-sm capitalize ${aiTarget === t ? "btn-primary" : "btn-secondary"}`}
              >
                {t}
              </button>
            ))}
          </div>
          <textarea
            value={aiPrompt}
            onChange={(e) => setAiPrompt(e.target.value)}
            placeholder={
              aiTarget === "doc"
                ? "e.g. A product marketing brief with sections for pain points, the solution, and who it's for — formal tone, purple headings."
                : "e.g. A high-energy 30-second social demo with captions and auto-zoom on clicks."
            }
            className="input min-h-[90px] resize-y"
          />
          <button onClick={buildWithAI} disabled={busy === "ai"} className="btn btn-primary">
            {busy === "ai" ? (
              <>
                <Spinner /> Building…
              </>
            ) : (
              "Generate skill"
            )}
          </button>
        </div>
      )}

      {/* templates */}
      <div className="mt-12 flex items-center justify-between">
        <h2 id="templates" className="text-lg font-semibold tracking-tight text-[var(--text)]">
          Start from a template
        </h2>
        <Link href="/skills/gallery" className="text-sm font-medium text-[var(--brand-2)]">
          Browse full gallery →
        </Link>
      </div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {TEMPLATES.map((t) => (
          <button
            key={t.name}
            onClick={() => fromTemplate(t)}
            disabled={busy === t.name}
            className="card card-hover overflow-hidden text-left"
          >
            <div className={`flex h-20 items-center justify-center bg-gradient-to-br ${t.grad} text-3xl`}>
              {busy === t.name ? <Spinner /> : t.icon}
            </div>
            <div className="p-4">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-[var(--text)]">{t.name}</span>
                <span className="badge bg-[#6d5dfb]/12 capitalize text-[var(--brand-2)]">{t.target}</span>
              </div>
              <p className="mt-1 line-clamp-2 text-xs text-[var(--text-2)]">{t.desc}</p>
            </div>
          </button>
        ))}
      </div>

      {/* your skills */}
      <h2 className="mt-12 text-lg font-semibold tracking-tight text-[var(--text)]">Your skills</h2>
      {skills.length === 0 ? (
        <p className="mt-3 text-sm text-[var(--text-2)]">No skills yet — build one above or install a template.</p>
      ) : (
        [
          ["Video", video],
          ["Document", doc],
        ] as const
      )
        .filter(([, list]) => list.length)
        .map(([label, list]) => (
          <div key={label} className="mt-5">
            <div className="label mb-2">{label}</div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {list.map((s) => (
                <Link key={s.id} href={`/skills/${s.id}`} className="card card-hover group relative flex gap-3 p-4">
                  <span className="flex h-11 w-11 flex-none items-center justify-center rounded-xl bg-gradient-to-br from-[#6d5dfb] to-[#a855f7] text-white">
                    {s.target === "video" ? "🎬" : "📄"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-semibold text-[var(--text)]">{s.name}</span>
                      <button
                        onClick={(e) => {
                          e.preventDefault();
                          deleteSkill(s.id).then(load);
                        }}
                        className="ml-auto text-[var(--text-3)] opacity-0 transition-opacity hover:text-red-400 group-hover:opacity-100"
                      >
                        ✕
                      </button>
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-xs text-[var(--text-2)]">
                      {s.description || "No description yet."}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {caps(s).map((c, i) => (
                        <span
                          key={i}
                          className="rounded-md border border-[var(--border)] bg-[var(--input-bg)] px-1.5 py-0.5 text-[10px] text-[var(--text-3)]"
                        >
                          {c}
                        </span>
                      ))}
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        ))}
    </main>
  );
}
