"use client";

import { Suspense, use, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  getGraph,
  getSessionDetail,
  getSessionStatus,
  getVideo,
  listPackages,
  listSkills,
  mediaUrl,
  patchVideo,
  regenerateDocument,
  rewriteLines,
  setKeepRanges,
  type BrandPackage,
  type Skill,
  type EditSpec,
  type GraphRow,
  type SessionDetail,
  type SessionStatus,
} from "@/lib/api";
import { Spinner, StatusDot } from "@/components/ui";
import { CropModal, ModalShell, RawTrimModal, resolveDuration } from "@/components/EditModals";
import { VoicePanel } from "@/components/VoicePanel";

/* Skills come from the Skills page (/skills). Each carries an AI `instruction`
   plus video settings (voice/speed/captions). Gradients are assigned from this
   source-defined palette so Tailwind always generates the classes. */
const GRADS = [
  "from-[#f97316] via-[#ec4899] to-[#8b5cf6]",
  "from-[#22c55e] via-[#10b981] to-[#0ea5e9]",
  "from-[#8b5cf6] via-[#6d5dfb] to-[#0ea5e9]",
  "from-[#6366f1] via-[#8b5cf6] to-[#d946ef]",
  "from-[#f43f5e] via-[#f97316] to-[#eab308]",
];

type VideoSkill = {
  key: string;
  name: string;
  grad: string;
  voice_id: string;
  speed: number;
  captions: boolean;
  motionZoom: boolean;
  instruction: string;
  pkg: string;
};
type DocSkill = { key: string; name: string; grad: string; instruction: string };

const str = (v: unknown, d: string) => (typeof v === "string" && v ? v : d);
const num = (v: unknown, d: number) => (typeof v === "number" ? v : d);

function toVideoSkill(s: Skill, i: number): VideoSkill {
  const st = s.settings || {};
  return {
    key: s.id,
    name: s.name,
    grad: GRADS[i % GRADS.length],
    voice_id: str(st.voice_id, "af_sarah"),
    speed: num(st.speed, 1),
    captions: st.captions !== false,
    motionZoom: st.motion_zoom === true,
    instruction: str(
      st.instruction,
      `Rewrite the narration in a ${str(st.tone, "clear, professional")} tone.${s.description ? " " + s.description : ""}`,
    ),
    pkg: str(st.package, ""),
  };
}
function toDocSkill(s: Skill, i: number): DocSkill {
  const st = s.settings || {};
  return {
    key: s.id,
    name: s.name,
    grad: GRADS[i % GRADS.length],
    instruction: str(
      st.instruction,
      `Rewrite the guide in a ${str(st.tone, "clear")} style.${s.description ? " " + s.description : ""}`,
    ),
  };
}
const FALLBACK_VIDEO: VideoSkill = { key: "std", name: "Standard", grad: GRADS[0], voice_id: "af_sarah", speed: 1, captions: true, motionZoom: false, instruction: "", pkg: "" };
const FALLBACK_DOC: DocSkill = { key: "std", name: "Standard", grad: GRADS[0], instruction: "" };

const mmss = (t: number) =>
  Number.isFinite(t) && t >= 0
    ? `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`
    : "0:00";
const eff = (s: { words: string[]; removed: number[] }) =>
  s.words.filter((_, i) => !s.removed.includes(i)).join(" ");

const STAGES = [
  { key: "media", label: "Analyzing footage" },
  { key: "whisper", label: "Transcribing narration" },
  { key: "merge", label: "Detecting scenes" },
  { key: "extract", label: "Building your script" },
];

export default function PreparePage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={null}>
      <PrepareInner params={params} />
    </Suspense>
  );
}

function PrepareInner({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const sid = useSearchParams().get("sid") ?? "";
  const intent = useSearchParams().get("intent"); // "doc" preselects guide-only
  const router = useRouter();

  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [status, setStatus] = useState<SessionStatus | null>(null);
  const [graph, setGraph] = useState<GraphRow | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [dur, setDur] = useState(0);
  const [modal, setModal] = useState<null | "trim" | "crop" | "voice" | "skill" | "docskill">(null);

  // what to generate
  const [wantVideo, setWantVideo] = useState(intent !== "doc");
  const [wantGuide, setWantGuide] = useState(true);
  const [packages, setPackages] = useState<BrandPackage[]>([]);
  const [videoSkills, setVideoSkills] = useState<VideoSkill[]>([]);
  const [docSkills, setDocSkills] = useState<DocSkill[]>([]);
  const [skill, setSkill] = useState<VideoSkill>(FALLBACK_VIDEO);
  const [pendingSkill, setPendingSkill] = useState<string>(FALLBACK_VIDEO.key);
  const [docSkill, setDocSkill] = useState<DocSkill>(FALLBACK_DOC);
  const [pendingDocSkill, setPendingDocSkill] = useState<string>(FALLBACK_DOC.key);

  // pull the skill presets from the Skills page
  useEffect(() => {
    listPackages().then(setPackages).catch(() => {});
    listSkills()
      .then((list) => {
        const vs = list.filter((s) => s.target === "video").map(toVideoSkill);
        const ds = list.filter((s) => s.target === "doc").map(toDocSkill);
        setVideoSkills(vs);
        setDocSkills(ds);
        if (vs[0]) {
          setSkill(vs[0]);
          setPendingSkill(vs[0].key);
        }
        if (ds[0]) {
          setDocSkill(ds[0]);
          setPendingDocSkill(ds[0].key);
        }
      })
      .catch(() => {});
  }, []);

  // staged edits (applied to the edit spec at generate time)
  const [crop, setCrop] = useState<EditSpec["crop"]>(undefined);
  const [voice, setVoice] = useState<{ voice_id: string; speed: number; use_original?: boolean } | null>(null);

  const [generating, setGenerating] = useState(false);
  const genRef = useRef(false);

  useEffect(() => {
    if (!sid) return;
    const refresh = () => {
      getSessionDetail(sid).then(setDetail).catch((e) => setError(String(e)));
      getSessionStatus(sid).then(setStatus).catch(() => {});
      getGraph(id).then(setGraph).catch(() => {});
    };
    refresh();
    const iv = setInterval(refresh, 2500);
    return () => clearInterval(iv);
  }, [id, sid]);

  const videoAsset = detail?.assets.find((a) => a.kind === "raw_video");
  const jobFor = (stage: string) => status?.jobs.find((j) => j.stage === stage);
  const doneStages = STAGES.filter((s) => jobFor(s.key)?.status === "done").length;
  const pct = graph ? 100 : Math.round((doneStages / STAGES.length) * 100);
  // Estimated length of the final generated video (≈ tightened source length).
  const finalSecs = dur ? Math.max(5, Math.round(dur * 0.85)) : null;

  const outputs = (wantVideo ? 1 : 0) + (wantGuide ? 1 : 0);

  async function generate() {
    if (genRef.current || outputs === 0) return;
    genRef.current = true;
    setGenerating(true);
    setError(null);
    try {
      // wait for the workflow graph (pipeline runs in the background)
      let g = graph;
      for (let i = 0; i < 240 && !g; i++) {
        await new Promise((r) => setTimeout(r, 2500));
        g = await getGraph(id).catch(() => null);
      }
      if (!g) throw new Error("processing did not finish — is the worker running?");

      // build the styled Step-by-Step Guide (independent of the video)
      if (wantGuide) {
        try {
          await regenerateDocument(id, docSkill.instruction);
        } catch {
          /* keep the plain doc if styling fails */
        }
      }

      if (wantVideo) {
        // apply the chosen skill + staged crop/voice to the edit spec
        const v = await getVideo(id);
        if (!v) throw new Error("video project not ready yet — try again in a moment");
        let spec = v.edit_spec;
        spec = {
          ...spec,
          voice: voice ?? { voice_id: skill.voice_id, speed: skill.speed, use_original: false },
          captions: { enabled: skill.captions },
          motion_zoom: skill.motionZoom,
          ...(crop?.enabled ? { crop } : {}),
        };
        // brand the video from the skill's Brand Package (intro/outro + logo + colours)
        if (skill.pkg) {
          const pk = packages.find((p) => p.name.toLowerCase() === skill.pkg.toLowerCase());
          if (pk) {
            const st = pk.settings as Record<string, string>;
            spec = {
              ...spec,
              intro: { enabled: true, title: st.intro || spec.title, duration_ms: 2200 },
              outro: { enabled: true, title: st.outro || "Thanks for watching", duration_ms: 1800 },
              brand: {
                logo_url: st.logo_url || "",
                primary_color: st.primary_color || "#6d5dfb",
                accent_color: st.accent_color || "#a855f7",
                font: st.font || "Geist",
                logo_position: st.logo_position || "Top Right",
              },
            };
          }
        }
        spec = (await patchVideo(id, spec)).edit_spec;
        // restyle the narration in the skill's voice (best-effort)
        try {
          const targets = spec.segments.map((s, i) => ({ i, t: eff(s) })).filter((x) => x.t.trim());
          if (targets.length) {
            const out = await rewriteLines(id, targets.map((x) => x.t), skill.instruction);
            const segs = [...spec.segments];
            targets.forEach((x, k) => {
              const words = (out[k] || x.t).trim().split(/\s+/).filter(Boolean);
              segs[x.i] = { ...segs[x.i], words, removed: [] };
            });
            await patchVideo(id, { ...spec, segments: segs });
          }
        } catch {
          /* keep verbatim narration if restyle fails */
        }
        router.push(`/projects/${id}/video`);
      } else {
        router.push(`/projects/${id}/document`);
      }
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setGenerating(false);
      genRef.current = false;
    }
  }

  const toolBtn =
    "inline-flex items-center gap-1.5 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3.5 py-2 text-sm font-medium text-[var(--text)] hover:bg-[var(--hover)] disabled:opacity-40";

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      {/* header */}
      <div className="flex items-center gap-3 border-b border-[var(--border)] bg-[var(--card)] px-6 py-4">
        <Link href="/" className="flex h-9 w-9 items-center justify-center rounded-full border border-[var(--border)] hover:bg-[var(--hover)]">
          ←
        </Link>
        <h1 className="text-lg font-semibold">
          {detail?.source_type === "upload" ? "Upload Video" : "New Recording"}
        </h1>
      </div>

      <div className="flex flex-col lg:flex-row">
        {/* left: preview + tools */}
        <div className="min-w-0 flex-1 border-r border-[var(--border)] p-6">
          <div className="mb-4 flex items-center justify-between gap-3">
            <span className="rounded-xl border border-[var(--border)] bg-[var(--card)] px-3.5 py-2 text-sm text-[var(--text)]">
              English ▾
            </span>
            <div className="flex items-center gap-2">
              <button onClick={() => setModal("crop")} disabled={!videoAsset} className={toolBtn}>
                ⛶ Crop {crop?.enabled && <span className="h-1.5 w-1.5 rounded-full bg-[#6d5dfb]" />}
              </button>
              <button onClick={() => setModal("trim")} disabled={!videoAsset} className={toolBtn}>
                ✂ Trim {detail?.trim_start_ms != null && <span className="h-1.5 w-1.5 rounded-full bg-[#6d5dfb]" />}
              </button>
              <button disabled title="Coming soon" className={toolBtn}>
                🌐 Translate
              </button>
              <button onClick={() => setModal("voice")} disabled={!videoAsset} className={toolBtn}>
                🎙 Voice {voice && <span className="h-1.5 w-1.5 rounded-full bg-[#6d5dfb]" />}
              </button>
            </div>
          </div>

          {videoAsset ? (
            <video
              src={mediaUrl(videoAsset.storage_key)}
              controls
              onLoadedMetadata={(e) => resolveDuration(e.currentTarget, setDur)}
              className="max-h-[62vh] w-full rounded-2xl bg-black"
            />
          ) : (
            <div className="flex aspect-video items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--card)] text-sm text-[var(--text-3)]">
              <Spinner /> Loading your video…
            </div>
          )}
          <p className="mt-3 text-center text-sm text-[var(--text-2)]">
            {detail ? `${detail.source_type === "upload" ? "" : ""}` : ""}
            {videoAsset ? videoAsset.storage_key.split("/").pop() : ""}
          </p>
        </div>

        {/* right: what to generate */}
        <aside className="w-full flex-none p-6 lg:w-[420px]">
          <h2 className="text-lg font-semibold">What do you want to generate</h2>
          <p className="mt-0.5 text-sm text-[var(--text-3)]">Pick one or more skills. You can edit everything later.</p>

          <div className="mt-5 grid grid-cols-2 gap-3">
            {/* Video card with skill badge */}
            <button
              onClick={() => setWantVideo((v) => !v)}
              className={`relative rounded-2xl border p-4 text-left transition-all ${
                wantVideo ? "border-[#6d5dfb] bg-[#6d5dfb]/5" : "border-[var(--border)] bg-[var(--card)]"
              }`}
            >
              <span
                onClick={(e) => {
                  e.stopPropagation();
                  setPendingSkill(skill.key);
                  setModal("skill");
                }}
                className="absolute -top-2.5 left-3 inline-flex cursor-pointer items-center gap-1 rounded-full bg-[#6d5dfb]/10 px-2.5 py-0.5 text-[11px] font-medium text-[#6d5dfb] ring-1 ring-[#6d5dfb]/30 hover:bg-[#6d5dfb]/20"
                title="Change video style"
              >
                {skill.name} ✎
              </span>
              <span
                className={`absolute right-3 top-3 flex h-5 w-5 items-center justify-center rounded-md text-[11px] ${
                  wantVideo ? "bg-[#6d5dfb] text-white" : "border border-[var(--border-strong)] bg-[var(--card)]"
                }`}
              >
                {wantVideo ? "✓" : ""}
              </span>
              <span className="text-xl">🎬</span>
              <div className="mt-3 text-sm font-medium">Video</div>
            </button>

            {/* Guide card with doc-style badge */}
            <button
              onClick={() => setWantGuide((v) => !v)}
              className={`relative rounded-2xl border p-4 text-left transition-all ${
                wantGuide ? "border-[#6d5dfb] bg-[#6d5dfb]/5" : "border-[var(--border)] bg-[var(--card)]"
              }`}
            >
              <span
                onClick={(e) => {
                  e.stopPropagation();
                  setPendingDocSkill(docSkill.key);
                  setModal("docskill");
                }}
                className="absolute -top-2.5 left-3 inline-flex cursor-pointer items-center gap-1 rounded-full bg-[#6d5dfb]/10 px-2.5 py-0.5 text-[11px] font-medium text-[#6d5dfb] ring-1 ring-[#6d5dfb]/30 hover:bg-[#6d5dfb]/20"
                title="Change guide style"
              >
                {docSkill.name} ✎
              </span>
              <span
                className={`absolute right-3 top-3 flex h-5 w-5 items-center justify-center rounded-md text-[11px] ${
                  wantGuide ? "bg-[#6d5dfb] text-white" : "border border-[var(--border-strong)] bg-[var(--card)]"
                }`}
              >
                {wantGuide ? "✓" : ""}
              </span>
              <span className="text-xl">📝</span>
              <div className="mt-3 text-sm font-medium">Step-by-Step Guide</div>
            </button>

            <CardCheck label="Assessment" icon="📋" disabled />
            <CardCheck label="FAQs" icon="❓" disabled />
          </div>

          <Link href="/skills" className="mt-3 inline-block text-sm text-[var(--text-2)] hover:text-[var(--text)]">
            View more
          </Link>

          <button
            onClick={generate}
            disabled={generating || outputs === 0 || !videoAsset}
            className="btn btn-primary mt-5 w-full bg-gradient-to-r from-[#6d5dfb] to-[var(--brand-2)] py-3"
          >
            {generating ? (
              <>
                <Spinner /> Generating… {pct}%
              </>
            ) : (
              "✨ Generate AI content"
            )}
          </button>
          {finalSecs !== null && (
            <p className="mt-2 text-center text-sm text-[#6d5dfb]">
              🎬 ≈ {mmss(finalSecs)} min final video
            </p>
          )}

          {generating && (
            <ol className="mt-4 space-y-2">
              {STAGES.map(({ key, label }) => {
                const st = graph ? "done" : jobFor(key)?.status;
                return (
                  <li key={key} className="flex items-center gap-2.5 text-sm text-[var(--text-2)]">
                    <StatusDot status={st} /> {label}
                  </li>
                );
              })}
              {wantVideo && (
                <li className="flex items-center gap-2.5 text-sm text-[var(--text-2)]">
                  <StatusDot status={graph ? "running" : undefined} /> Styling as {skill.name}
                </li>
              )}
            </ol>
          )}

          {error && (
            <p className="mt-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>
          )}
        </aside>
      </div>

      {/* ---- modals ---- */}
      {modal === "trim" && videoAsset && (
        <RawTrimModal
          source={videoAsset.storage_key}
          onCancel={() => setModal(null)}
          onSave={async (ranges) => {
            setModal(null);
            try {
              await setKeepRanges(sid, ranges); // reprocesses keeping only these blocks
            } catch (err) {
              setError(String(err));
            }
          }}
        />
      )}
      {modal === "crop" && videoAsset && (
        <CropModal
          source={videoAsset.storage_key}
          crop={crop}
          onCancel={() => setModal(null)}
          onSave={(c) => {
            setCrop(c);
            setModal(null);
          }}
        />
      )}
      {modal === "voice" && (
        <ModalShell
          title="AI Voice"
          onClose={() => setModal(null)}
          footer={
            <div className="ml-auto flex gap-2">
              <button onClick={() => setModal(null)} className="btn btn-primary">
                Done
              </button>
            </div>
          }
        >
          <VoicePanel
            value={voice ?? { voice_id: skill.voice_id, speed: skill.speed, use_original: false }}
            onChange={(patch) =>
              setVoice((v) => ({ ...(v ?? { voice_id: skill.voice_id, speed: skill.speed, use_original: false }), ...patch }))
            }
          />
        </ModalShell>
      )}
      {modal === "skill" && (
        <ModalShell
          title="Create more outputs"
          onClose={() => setModal(null)}
          footer={
            <>
              <span className="text-sm text-[var(--text-2)]">1 output selected</span>
              <div className="ml-auto flex gap-2">
                <button onClick={() => setModal(null)} className="btn btn-secondary">
                  Cancel
                </button>
                <button
                  onClick={() => {
                    setSkill(videoSkills.find((s) => s.key === pendingSkill) ?? skill);
                    setWantVideo(true);
                    setModal(null);
                  }}
                  className="btn btn-primary"
                >
                  Confirm selection
                </button>
              </div>
            </>
          }
        >
          <p className="-mt-2 mb-4 text-sm text-[var(--text-3)]">Pick one or more skills to generate from your recording</p>
          <div className="grid grid-cols-1 gap-4 pb-2 sm:grid-cols-3">
            {videoSkills.map((s) => {
              const on = pendingSkill === s.key;
              return (
                <button
                  key={s.key}
                  onClick={() => setPendingSkill(s.key)}
                  className={`overflow-hidden rounded-xl border text-left transition-all ${
                    on ? "border-[#6d5dfb] ring-1 ring-[#6d5dfb]" : "border-[var(--border)] hover:border-[var(--border-strong)]"
                  }`}
                >
                  {/* thumbnail */}
                  <div className={`relative h-28 bg-gradient-to-br ${s.grad} p-3`}>
                    <div className="h-full rounded-md bg-white/95 p-2">
                      <div className="h-1.5 w-2/3 rounded bg-[#e5e7eb]" />
                      <div className="mt-1.5 h-1.5 w-1/2 rounded bg-[var(--border)]" />
                      <div className="mt-1.5 h-1.5 w-3/5 rounded bg-[var(--border)]" />
                      <span className="absolute bottom-2 right-4 flex h-8 w-8 items-center justify-center rounded bg-gradient-to-br from-[#6d5dfb] to-[#a855f7] text-[10px] text-white">
                        🧑
                      </span>
                    </div>
                  </div>
                  <div className={`px-3 py-2.5 text-center text-sm font-medium ${on ? "text-[#6d5dfb]" : "text-[var(--text)]"}`}>
                    {s.name}
                  </div>
                </button>
              );
            })}
          </div>
        </ModalShell>
      )}

      {modal === "docskill" && (
        <ModalShell
          title="Guide style"
          onClose={() => setModal(null)}
          footer={
            <>
              <span className="text-sm text-[var(--text-2)]">1 style selected</span>
              <div className="ml-auto flex gap-2">
                <button onClick={() => setModal(null)} className="btn btn-secondary">
                  Cancel
                </button>
                <button
                  onClick={() => {
                    setDocSkill(docSkills.find((s) => s.key === pendingDocSkill) ?? docSkill);
                    setWantGuide(true);
                    setModal(null);
                  }}
                  className="btn btn-primary"
                >
                  Confirm selection
                </button>
              </div>
            </>
          }
        >
          <p className="-mt-2 mb-4 text-sm text-[var(--text-3)]">Choose how your Step-by-Step Guide is written</p>
          <div className="grid grid-cols-1 gap-4 pb-2 sm:grid-cols-3">
            {docSkills.map((s) => {
              const on = pendingDocSkill === s.key;
              return (
                <button
                  key={s.key}
                  onClick={() => setPendingDocSkill(s.key)}
                  className={`overflow-hidden rounded-xl border text-left transition-all ${
                    on ? "border-[#6d5dfb] ring-1 ring-[#6d5dfb]" : "border-[var(--border)] hover:border-[var(--border-strong)]"
                  }`}
                >
                  <div className={`relative h-28 bg-gradient-to-br ${s.grad} p-3`}>
                    <div className="h-full rounded-md bg-white/95 p-2">
                      <div className="h-1.5 w-1/2 rounded bg-[#e5e7eb]" />
                      <div className="mt-1.5 h-1.5 w-4/5 rounded bg-[var(--border)]" />
                      <div className="mt-1.5 h-1.5 w-3/4 rounded bg-[var(--border)]" />
                      <div className="mt-1.5 h-1.5 w-2/3 rounded bg-[var(--border)]" />
                    </div>
                  </div>
                  <div className={`px-3 py-2.5 text-center text-sm font-medium ${on ? "text-[#6d5dfb]" : "text-[var(--text)]"}`}>
                    {s.name}
                  </div>
                </button>
              );
            })}
          </div>
        </ModalShell>
      )}
    </div>
  );
}

function CardCheck({
  label,
  icon,
  on,
  onClick,
  disabled,
}: {
  label: string;
  icon: string;
  on?: boolean;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={disabled ? "Coming soon" : label}
      className={`relative rounded-2xl border p-4 text-left transition-all ${
        on ? "border-[#6d5dfb] bg-[#6d5dfb]/5" : "border-[var(--border)] bg-[var(--card)]"
      } ${disabled ? "opacity-50" : ""}`}
    >
      <span
        className={`absolute right-3 top-3 flex h-5 w-5 items-center justify-center rounded-md text-[11px] ${
          on ? "bg-[#6d5dfb] text-white" : "border border-[var(--border-strong)] bg-[var(--card)]"
        }`}
      >
        {on ? "✓" : ""}
      </span>
      <span className="text-xl">{icon}</span>
      <div className="mt-3 text-sm font-medium">{label}</div>
    </button>
  );
}
