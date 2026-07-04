"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createSkill } from "@/lib/api";
import { SKILL_GALLERY, type GalleryItem } from "@/lib/skillGallery";
import { skillToMarkdown } from "@/lib/skillmd";
import { Spinner } from "@/components/ui";

const CATS = ["All", "Video", "Docs"] as const;

function caps(it: GalleryItem): string[] {
  const st = it.settings;
  const out: string[] = [];
  if (typeof st.voice_id === "string") out.push(`🎙 ${st.voice_id}`);
  if (st.captions === true) out.push("CC");
  if (st.motion_zoom === true) out.push("⛶ auto-zoom");
  if (typeof st.aspect === "string") out.push(st.aspect as string);
  const secs = Array.isArray(st.sections) ? st.sections.length : 0;
  if (secs) out.push(`${secs} sections`);
  return out.slice(0, 4);
}

export default function SkillGallery() {
  const router = useRouter();
  const [cat, setCat] = useState<(typeof CATS)[number]>("All");
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [preview, setPreview] = useState<GalleryItem | null>(null);

  const items = useMemo(() => {
    const t = q.trim().toLowerCase();
    return SKILL_GALLERY.filter(
      (it) =>
        (cat === "All" || it.category === cat) &&
        (!t || it.name.toLowerCase().includes(t) || it.description.toLowerCase().includes(t)),
    );
  }, [cat, q]);

  async function install(it: GalleryItem) {
    setBusy(it.slug);
    try {
      const s = await createSkill({
        name: it.name,
        description: it.description,
        target: it.target,
        settings: it.settings,
      });
      router.push(`/skills/${s.id}`);
    } catch {
      setBusy(null);
    }
  }

  const md = (it: GalleryItem) =>
    skillToMarkdown({ id: it.slug, name: it.name, description: it.description, target: it.target, settings: it.settings });

  return (
    <main className="mx-auto max-w-5xl px-8 py-10">
      <div className="mb-1 text-sm text-[var(--text-3)]">
        <Link href="/skills" className="hover:text-[var(--text)]">
          Skills
        </Link>{" "}
        / Gallery
      </div>
      <h1 className="text-3xl font-semibold tracking-tight text-[var(--text)]">Skill Gallery</h1>
      <p className="mt-1.5 text-[15px] text-[var(--text-2)]">
        Ready-made skills — install one in a click, then tweak it to taste.
      </p>

      {/* search + category */}
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-sm">
          <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-3)]">⌕</span>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search skills…" className="input rounded-full pl-9" />
        </div>
        <div className="flex items-center gap-1.5">
          {CATS.map((c) => (
            <button
              key={c}
              onClick={() => setCat(c)}
              className={`rounded-full border px-3.5 py-1.5 text-sm font-medium ${
                cat === c
                  ? "border-[#6d5dfb] bg-[#6d5dfb]/10 text-[var(--brand-2)]"
                  : "border-[var(--border)] bg-[var(--card)] text-[var(--text-2)] hover:text-[var(--text)]"
              }`}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      {/* cards */}
      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((it) => (
          <div key={it.slug} className="card card-hover flex flex-col overflow-hidden">
            <div className={`flex h-20 items-center justify-center bg-gradient-to-br ${it.grad} text-3xl`}>{it.icon}</div>
            <div className="flex flex-1 flex-col p-4">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-[var(--text)]">{it.name}</span>
                <span className="badge bg-[#6d5dfb]/12 capitalize text-[var(--brand-2)]">{it.target}</span>
              </div>
              <p className="mt-1 line-clamp-2 text-xs text-[var(--text-2)]">{it.description}</p>
              <div className="mt-2 flex flex-wrap gap-1">
                {caps(it).map((c, i) => (
                  <span key={i} className="rounded-md border border-[var(--border)] bg-[var(--input-bg)] px-1.5 py-0.5 text-[10px] text-[var(--text-3)]">
                    {c}
                  </span>
                ))}
              </div>
              <div className="mt-auto flex gap-2 pt-3">
                <button onClick={() => install(it)} disabled={busy === it.slug} className="btn btn-primary btn-sm flex-1">
                  {busy === it.slug ? (
                    <>
                      <Spinner /> Installing…
                    </>
                  ) : (
                    "＋ Install"
                  )}
                </button>
                <button onClick={() => setPreview(it)} className="btn btn-secondary btn-sm">
                  {"</>"}
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* SKILL.md preview */}
      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setPreview(null)}>
          <div className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 border-b border-[var(--border)] px-5 py-3">
              <span className="font-semibold text-[var(--text)]">{preview.name} · SKILL.md</span>
              <button onClick={() => navigator.clipboard?.writeText(md(preview))} className="btn btn-ghost btn-sm ml-auto">
                ⧉ Copy
              </button>
              <button onClick={() => setPreview(null)} className="btn btn-ghost btn-sm">
                ✕
              </button>
            </div>
            <pre className="overflow-auto whitespace-pre-wrap px-5 py-4 font-mono text-xs text-[var(--text-2)]">{md(preview)}</pre>
            <div className="flex justify-end gap-2 border-t border-[var(--border)] px-5 py-3">
              <button onClick={() => install(preview)} disabled={busy === preview.slug} className="btn btn-primary btn-sm">
                ＋ Install
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
