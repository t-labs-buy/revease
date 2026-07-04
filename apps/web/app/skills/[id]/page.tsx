"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createSkill, deleteSkill, getSkill, updateSkill, type Skill } from "@/lib/api";
import { skillToMarkdown } from "@/lib/skillmd";
import { Spinner } from "@/components/ui";

const FONT_FAMILIES = ["Geist", "Inter", "Arial", "Georgia", "Times New Roman", "Courier New"];
const LOGO_POS = ["Top Left", "Top Center", "Top Right", "Bottom Left", "Bottom Right"];

type Section = { title: string; description: string; include_screenshots: boolean };
type FontRule = { family: string; color: string; size: number };
type Fonts = { heading1: FontRule; heading2: FontRule; heading3: FontRule; paragraph: FontRule };

const DEFAULT_FONTS: Fonts = {
  heading1: { family: "Geist", color: "#6655A5", size: 36 },
  heading2: { family: "Geist", color: "#544F64", size: 30 },
  heading3: { family: "Geist", color: "#747391", size: 24 },
  paragraph: { family: "Geist", color: "#949494", size: 16 },
};

function parse(skill: Skill) {
  const st = skill.settings || {};
  return {
    name: skill.name,
    description: skill.description || "",
    target: (skill.target as "video" | "doc") || "doc",
    tags: (st.tags as string[]) || [],
    overall: (st.overall_instructions as string) || "",
    pkg: (st.package as string) || "",
    sections: ((st.sections as Section[]) || []).map((s) => ({
      title: s.title || "",
      description: s.description || "",
      include_screenshots: !!s.include_screenshots,
    })),
    fonts: { ...DEFAULT_FONTS, ...((st.formatting as { fonts?: Fonts })?.fonts || {}) } as Fonts,
    logoPos: ((st.formatting as { logo_position?: string })?.logo_position as string) || "Top Left",
    blockQuote:
      ((st.formatting as { block_quote?: { color: string; family: string } })?.block_quote) || {
        color: "#C2D2EA",
        family: "Geist",
      },
    // video-only
    voice_id: (st.voice_id as string) || "af_sarah",
    speed: (st.speed as number) ?? 1,
    captions: st.captions !== false,
    motion_zoom: st.motion_zoom === true,
    instruction: (st.instruction as string) || "",
  };
}

export default function SkillDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [skill, setSkill] = useState<Skill | null>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showMd, setShowMd] = useState(false);
  const [f, setF] = useState<ReturnType<typeof parse> | null>(null);

  function exportMd() {
    if (!skill) return;
    const md = skillToMarkdown(skill);
    const blob = new Blob([md], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${skill.name.replace(/[^\w]+/g, "-").toLowerCase() || "skill"}.SKILL.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  useEffect(() => {
    getSkill(id)
      .then((s) => {
        setSkill(s);
        setF(parse(s));
      })
      .catch((e) => setError(String(e)));
  }, [id]);

  if (error) return <main className="p-10 text-sm text-red-400">{error}</main>;
  if (!skill || !f) return <main className="flex items-center gap-2 p-10 text-sm text-[var(--text-2)]"><Spinner /> Loading…</main>;

  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF({ ...f, [k]: v });
  const setFont = (lvl: keyof Fonts, patch: Partial<FontRule>) =>
    set("fonts", { ...f.fonts, [lvl]: { ...f.fonts[lvl], ...patch } });

  async function save() {
    if (!f) return;
    setSaving(true);
    try {
      const settings = {
        tags: f.tags,
        overall_instructions: f.overall,
        package: f.pkg,
        sections: f.sections,
        formatting: { fonts: f.fonts, logo_position: f.logoPos, block_quote: f.blockQuote },
        voice_id: f.voice_id,
        speed: f.speed,
        captions: f.captions,
        motion_zoom: f.motion_zoom,
        instruction: f.instruction,
      };
      const s = await updateSkill(id, { name: f.name, description: f.description, target: f.target, settings });
      setSkill(s);
      setEditing(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  async function duplicate() {
    if (!f) return;
    const copy = await createSkill({
      name: `${f.name} (Copy)`,
      description: f.description,
      target: f.target,
      settings: skill!.settings,
    });
    router.push(`/skills/${copy.id}`);
  }

  async function remove() {
    if (!confirm("Delete this skill?")) return;
    await deleteSkill(id);
    router.push("/skills");
  }

  return (
    <main className="min-h-screen">
      {/* header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] px-6 py-3.5">
        <Link href="/skills" className="flex items-center gap-2 text-sm font-medium text-[var(--text)]">
          <span className="text-[var(--text-3)]">‹</span> Skills / {f.name}
        </Link>
        <div className="flex items-center gap-2">
          {editing ? (
            <>
              <button onClick={() => { setF(parse(skill)); setEditing(false); }} className="btn btn-secondary btn-sm">
                Cancel
              </button>
              <button onClick={save} disabled={saving} className="btn btn-primary btn-sm">
                {saving ? "Saving…" : "Save"}
              </button>
            </>
          ) : (
            <button onClick={() => setEditing(true)} className="btn btn-primary btn-sm">
              ✎ Edit
            </button>
          )}
          <button
            onClick={() => setShowMd((v) => !v)}
            className={`btn btn-secondary btn-sm ${showMd ? "ring-1 ring-[#6d5dfb]" : ""}`}
          >
            {"</> SKILL.md"}
          </button>
          <button onClick={exportMd} className="btn btn-secondary btn-sm" title="Download SKILL.md">
            ⬇ Export
          </button>
          <button onClick={duplicate} className="btn btn-secondary btn-sm">
            ⧉ Duplicate
          </button>
          <button onClick={remove} className="btn btn-sm border border-red-500/40 text-red-500 hover:bg-red-500/10">
            🗑 Delete
          </button>
        </div>
      </div>

      {showMd && (
        <div className="mx-auto mt-4 max-w-3xl px-6">
          <div className="card overflow-hidden">
            <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-2">
              <span className="text-sm font-medium text-[var(--text-2)]">SKILL.md</span>
              <button
                onClick={() => navigator.clipboard?.writeText(skillToMarkdown(skill!))}
                className="btn btn-ghost btn-sm ml-auto"
              >
                ⧉ Copy
              </button>
            </div>
            <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap px-4 py-3 font-mono text-xs text-[var(--text-2)]">
              {skillToMarkdown(skill!)}
            </pre>
          </div>
        </div>
      )}

      <div className="mx-auto max-w-3xl px-6 py-8">
        {/* title */}
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-[#f59e0b] to-[#ef4444] text-lg">
            🎯
          </span>
          {editing ? (
            <input
              value={f.name}
              onChange={(e) => set("name", e.target.value)}
              className="input flex-1 text-lg font-semibold"
            />
          ) : (
            <h1 className="text-xl font-semibold text-[var(--text)]">{f.name}</h1>
          )}
          <span className="badge bg-[#6d5dfb]/15 capitalize text-[var(--brand-2)]">{f.target}</span>
        </div>

        {/* tags */}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          {f.tags.map((t, i) => (
            <span key={i} className="inline-flex items-center gap-1 rounded-full bg-[#6d5dfb]/10 px-2.5 py-1 text-xs font-medium text-[var(--brand-2)]">
              {t}
              {editing && (
                <button onClick={() => set("tags", f.tags.filter((_, j) => j !== i))} className="text-[var(--text-3)] hover:text-red-400">
                  ×
                </button>
              )}
            </span>
          ))}
          {editing && (
            <input
              placeholder="+ tag, press Enter"
              onKeyDown={(e) => {
                const v = (e.target as HTMLInputElement).value.trim();
                if (e.key === "Enter" && v) {
                  set("tags", [...f.tags, v]);
                  (e.target as HTMLInputElement).value = "";
                }
              }}
              className="input w-40 py-1 text-xs"
            />
          )}
        </div>

        {/* Brand Package */}
        <Group title="Brand Package">
          {editing ? (
            <input
              value={f.pkg}
              onChange={(e) => set("pkg", e.target.value)}
              placeholder="Package name from Library → Brand Packages (e.g. Acme Corp)"
              className="input"
            />
          ) : (
            <p className="text-sm text-[var(--text-2)]">
              {f.pkg ? (
                <>Uses the <b className="text-[var(--text)]">{f.pkg}</b> brand package (intro/outro, logo, colours).</>
              ) : (
                "No brand package — generated output uses default styling."
              )}
            </p>
          )}
        </Group>

        {/* Overall Instructions */}
        <Group title="Overall Instructions">
          {editing ? (
            <textarea
              value={f.overall}
              onChange={(e) => set("overall", e.target.value)}
              placeholder="Global instructions for the AI (tone, formatting, what to output)…"
              className="input min-h-[120px] resize-y text-sm leading-relaxed"
            />
          ) : (
            <p className="whitespace-pre-wrap rounded-xl border border-[var(--border)] bg-[var(--input-bg)] p-4 text-sm leading-relaxed text-[var(--text-2)]">
              {f.overall || "—"}
            </p>
          )}
        </Group>

        {/* Sections (doc) */}
        {f.target === "doc" && (
          <Group title="Sections">
            <div className="space-y-3">
              {f.sections.map((s, i) => (
                <div key={i} className="rounded-xl border border-[var(--border)] p-4">
                  {editing ? (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <input
                          value={s.title}
                          onChange={(e) => set("sections", f.sections.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))}
                          placeholder="Section title"
                          className="input font-medium"
                        />
                        <button onClick={() => set("sections", f.sections.filter((_, j) => j !== i))} className="btn btn-ghost btn-sm text-red-400">
                          ✕
                        </button>
                      </div>
                      <textarea
                        value={s.description}
                        onChange={(e) => set("sections", f.sections.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))}
                        placeholder="What should this section contain? (the AI prompt for this section)"
                        className="input min-h-[60px] resize-y text-sm"
                      />
                    </div>
                  ) : (
                    <>
                      <div className="text-sm font-semibold text-[var(--text)]">{s.title}</div>
                      <p className="mt-1 text-sm text-[var(--text-2)]">{s.description}</p>
                    </>
                  )}
                  <label className="mt-2 flex items-center gap-2 text-sm text-[var(--text-2)]">
                    <input
                      type="checkbox"
                      checked={s.include_screenshots}
                      disabled={!editing}
                      onChange={(e) => set("sections", f.sections.map((x, j) => (j === i ? { ...x, include_screenshots: e.target.checked } : x)))}
                      className="accent-[#6d5dfb]"
                    />
                    🖼 Include screenshots
                  </label>
                </div>
              ))}
              {editing && (
                <button
                  onClick={() => set("sections", [...f.sections, { title: "New section", description: "", include_screenshots: false }])}
                  className="w-full rounded-xl border border-dashed border-[var(--border-strong)] py-2 text-sm font-medium text-[var(--brand-2)] hover:bg-[#6d5dfb]/5"
                >
                  + Add section
                </button>
              )}
              {f.sections.length === 0 && !editing && <p className="text-sm text-[var(--text-3)]">No sections.</p>}
            </div>
          </Group>
        )}

        {/* Video settings */}
        {f.target === "video" && (
          <Group title="Video settings">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Voice">
                {editing ? (
                  <select value={f.voice_id} onChange={(e) => set("voice_id", e.target.value)} className="input">
                    {["af_sarah", "af_bella", "am_adam", "am_michael", "bf_emma", "bm_george"].map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                ) : (
                  <Val>{f.voice_id}</Val>
                )}
              </Field>
              <Field label="Speed">
                {editing ? (
                  <input type="number" min={0.75} max={1.5} step={0.05} value={f.speed} onChange={(e) => set("speed", Number(e.target.value))} className="input" />
                ) : (
                  <Val>{f.speed}×</Val>
                )}
              </Field>
              <label className="flex items-center gap-2 text-sm text-[var(--text-2)]">
                <input type="checkbox" checked={f.captions} disabled={!editing} onChange={(e) => set("captions", e.target.checked)} className="accent-[#6d5dfb]" /> Captions
              </label>
              <label className="flex items-center gap-2 text-sm text-[var(--text-2)]">
                <input type="checkbox" checked={f.motion_zoom} disabled={!editing} onChange={(e) => set("motion_zoom", e.target.checked)} className="accent-[#6d5dfb]" /> Auto-zoom on clicks
              </label>
            </div>
            <Field label="AI instruction" className="mt-3">
              {editing ? (
                <textarea value={f.instruction} onChange={(e) => set("instruction", e.target.value)} className="input min-h-[70px] resize-y text-sm" />
              ) : (
                <p className="text-sm text-[var(--text-2)]">{f.instruction || "—"}</p>
              )}
            </Field>
          </Group>
        )}

        {/* Formatting Rules */}
        <Group title="Formatting Rules">
          <div className="rounded-xl border border-[var(--border)] p-4">
            <div className="grid grid-cols-[100px_1fr_90px_1.4fr] items-center gap-3 border-b border-[var(--border)] pb-2 text-xs font-semibold text-[var(--text)]">
              <span>Font Type</span>
              <span>Font Family</span>
              <span>Font Colour</span>
              <span>Font Size</span>
            </div>
            {(
              [
                ["Heading 1", "heading1"],
                ["Heading 2", "heading2"],
                ["Heading 3", "heading3"],
                ["Paragraph", "paragraph"],
              ] as const
            ).map(([label, key]) => {
              const r = f.fonts[key];
              return (
                <div key={key} className="grid grid-cols-[100px_1fr_90px_1.4fr] items-center gap-3 py-2.5 text-sm">
                  <span className="text-[var(--text)]">{label}</span>
                  {editing ? (
                    <select value={r.family} onChange={(e) => setFont(key, { family: e.target.value })} className="input py-1.5">
                      {FONT_FAMILIES.map((ff) => (
                        <option key={ff}>{ff}</option>
                      ))}
                    </select>
                  ) : (
                    <span className="text-[var(--text-2)]" style={{ fontFamily: r.family }}>{r.family}</span>
                  )}
                  <div className="flex items-center gap-1.5">
                    <input
                      type="color"
                      value={r.color}
                      disabled={!editing}
                      onChange={(e) => setFont(key, { color: e.target.value })}
                      className="h-5 w-5 rounded border border-[var(--border)] bg-transparent"
                    />
                    <span className="text-xs text-[var(--text-3)]">{r.color.replace("#", "").toUpperCase()}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="range"
                      min={10}
                      max={48}
                      value={r.size}
                      disabled={!editing}
                      onChange={(e) => setFont(key, { size: Number(e.target.value) })}
                      className="flex-1 accent-[#6d5dfb]"
                    />
                    <span className="w-12 rounded-lg border border-[var(--border)] px-2 py-0.5 text-center text-xs">{r.size}pt</span>
                  </div>
                </div>
              );
            })}

            <div className="mt-4 flex items-center justify-between border-t border-[var(--border)] pt-3">
              <span className="text-sm font-semibold text-[var(--text)]">Logo Positioning</span>
              {editing ? (
                <select value={f.logoPos} onChange={(e) => set("logoPos", e.target.value)} className="input w-40 py-1.5">
                  {LOGO_POS.map((p) => (
                    <option key={p}>{p}</option>
                  ))}
                </select>
              ) : (
                <Val>{f.logoPos}</Val>
              )}
            </div>

            <div className="mt-3 flex items-center justify-between border-t border-[var(--border)] pt-3">
              <span className="text-sm font-semibold text-[var(--text)]">Block Quote</span>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  value={f.blockQuote.color}
                  disabled={!editing}
                  onChange={(e) => set("blockQuote", { ...f.blockQuote, color: e.target.value })}
                  className="h-5 w-5 rounded border border-[var(--border)] bg-transparent"
                />
                <span className="text-xs text-[var(--text-3)]">{f.blockQuote.color.replace("#", "").toUpperCase()}</span>
                {editing ? (
                  <select value={f.blockQuote.family} onChange={(e) => set("blockQuote", { ...f.blockQuote, family: e.target.value })} className="input w-32 py-1.5">
                    {FONT_FAMILIES.map((ff) => (
                      <option key={ff}>{ff}</option>
                    ))}
                  </select>
                ) : (
                  <Val>{f.blockQuote.family}</Val>
                )}
              </div>
            </div>
          </div>
        </Group>
      </div>
    </main>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <section className="mt-8">
      <button onClick={() => setOpen((v) => !v)} className="flex items-center gap-2 text-sm font-semibold text-[var(--text)]">
        <span className={`text-[var(--text-3)] transition-transform ${open ? "" : "-rotate-90"}`}>▾</span>
        {title}
      </button>
      {open && <div className="mt-3">{children}</div>}
    </section>
  );
}
function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <div className="label mb-1">{label}</div>
      {children}
    </div>
  );
}
const Val = ({ children }: { children: React.ReactNode }) => (
  <span className="text-sm text-[var(--text-2)]">{children}</span>
);
