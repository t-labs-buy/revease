"use client";

import { Suspense, use, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  activeCrop,
  getGraph,
  getSessionDetail,
  getSessionStatus,
  getVideo,
  mediaUrl,
  patchVideo,
  setKeepRanges,
  type CropRegion,
  type EditSpec,
  type GraphRow,
  type SessionDetail,
  type SessionStatus,
} from "@/lib/api";
import { Spinner, StatusDot } from "@/components/ui";
import { CropModal, ModalShell, RawTrimModal, resolveDuration } from "@/components/EditModals";
import { VoicePanel } from "@/components/VoicePanel";

const mmss = (t: number) =>
  Number.isFinite(t) && t >= 0
    ? `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`
    : "0:00";
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
  const wantDoc = useSearchParams().get("intent") === "doc"; // "New doc" flow → open the guide
  const router = useRouter();

  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [status, setStatus] = useState<SessionStatus | null>(null);
  const [graph, setGraph] = useState<GraphRow | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [dur, setDur] = useState(0);
  const [modal, setModal] = useState<null | "trim" | "crop" | "voice">(null);

  // staged edits (applied to the edit spec at generate time)
  const [crops, setCrops] = useState<CropRegion[]>([]);
  const [cur, setCur] = useState(0); // preview playhead — picks the active crop
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
  const processed = !!graph;

  async function generate() {
    if (genRef.current) return;
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

      if (wantDoc) {
        router.push(`/projects/${id}/document`);
        return;
      }
      const v = await getVideo(id);
      if (!v) throw new Error("video project not ready yet — try again in a moment");
      // apply the staged crop/voice tweaks, then open the editor
      const next: EditSpec = {
        ...v.edit_spec,
        ...(voice ? { voice: { ...v.edit_spec.voice, ...voice } } : {}),
        ...(crops.length ? { crops } : {}),
      };
      await patchVideo(id, next);
      router.push(`/projects/${id}/video`);
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      setGenerating(false);
      genRef.current = false;
    }
  }

  const toolBtn =
    "inline-flex items-center gap-1.5 rounded-xl border border-[var(--border)] bg-[var(--card)] px-3.5 py-2 text-sm font-medium text-[var(--text)] hover:bg-[var(--hover)] disabled:opacity-40";

  // Show the staged crop for real: reframe the preview so the cropped region
  // fills the player (same math the final render uses). Multi-range crops —
  // the playhead picks which region is in effect. Region is clamped so
  // x+w / y+h can never exceed the frame.
  const crop = activeCrop(crops, cur * 1000);
  const cw = Math.min(1, Math.max(0.05, crop?.w ?? 1));
  const ch = Math.min(1, Math.max(0.05, crop?.h ?? 1));
  const cx = Math.min(Math.max(0, crop?.x ?? 0), 1 - cw);
  const cy = Math.min(Math.max(0, crop?.y ?? 0), 1 - ch);
  const cropOn = !!crop && (cw < 0.999 || ch < 0.999 || cx > 0.001 || cy > 0.001);
  // Uniform cover-scale about the region center, then shift that center to the
  // middle of the frame — same "crop, then cover" the render does, so the
  // preview shows exactly the selected content with no stretch and no padding.
  const cropScale = Math.max(1 / cw, 1 / ch);
  const cropStyle: React.CSSProperties = cropOn
    ? {
        transform: `translate(${((0.5 - (cx + cw / 2)) * 100).toFixed(2)}%, ${(
          (0.5 - (cy + ch / 2)) * 100
        ).toFixed(2)}%) scale(${cropScale.toFixed(4)})`,
        transformOrigin: `${((cx + cw / 2) * 100).toFixed(2)}% ${((cy + ch / 2) * 100).toFixed(2)}%`,
      }
    : {};

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text)]">
      {/* header — back · title + breadcrumb · status pill · avatar */}
      <div className="flex items-center gap-3 border-b border-[var(--border)] bg-[var(--card)] px-6 py-3.5">
        <Link
          href="/"
          className="flex h-9 w-9 flex-none items-center justify-center rounded-full border border-[var(--border)] hover:bg-[var(--hover)]"
        >
          ←
        </Link>
        <div className="flex min-w-0 items-baseline gap-2.5">
          <h1 className="text-lg font-semibold">
            {detail?.source_type === "upload" ? "Upload Video" : "New Recording"}
          </h1>
          <span className="truncate text-sm text-[var(--text-3)]">Studio / New project</span>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <span
            className={`inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm ${
              processed
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-500"
                : "border-[var(--border)] bg-[var(--card)] text-[var(--text-2)]"
            }`}
          >
            <span className={`h-2 w-2 rounded-full ${processed ? "bg-emerald-500" : "animate-pulse bg-amber-400"}`} />
            {processed ? "Video processed" : "Processing video…"}
          </span>
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#6d5dfb] text-sm font-semibold text-white">
            R
          </span>
        </div>
      </div>

      <div className="mx-auto flex max-w-[1400px] flex-col gap-6 p-6 lg:flex-row">
        {/* left — player + tools + filename */}
        <div className="min-w-0 flex-1">
          <div className="overflow-hidden rounded-2xl bg-black shadow-lg ring-1 ring-[var(--border)]">
            {videoAsset ? (
              <div style={cropStyle}>
                <video
                  src={mediaUrl(videoAsset.storage_key)}
                  controls
                  onLoadedMetadata={(e) => resolveDuration(e.currentTarget, setDur)}
                  onTimeUpdate={(e) => setCur(e.currentTarget.currentTime)}
                  className="max-h-[62vh] w-full"
                />
              </div>
            ) : (
              <div className="flex aspect-video items-center justify-center text-sm text-[var(--text-3)]">
                <Spinner /> Loading your video…
              </div>
            )}
          </div>

          {/* Toolbar — shelved. Every tool is drawn but inert, with a note on
              top pointing at where the real thing lives. The modals below stay
              wired up, so re-enabling one is just dropping its `disabled`. */}
          <div className="relative mt-4 inline-block">
            <div className="inline-flex select-none items-center gap-2 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-2">
              <button disabled className={toolBtn}>
                ⛶ Crop
              </button>
              <button disabled className={toolBtn}>
                ✂ Trim
              </button>
              <button disabled className={toolBtn}>
                🌐 Translate
              </button>
              <button disabled className={toolBtn}>
                🎙 Voice
              </button>
              <span className="rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3.5 py-2 text-sm text-[var(--text-2)] opacity-40">
                English ▾
              </span>
            </div>
            <span className="pointer-events-none absolute inset-0 flex items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--card)]/95 px-4 text-center text-sm font-semibold text-[var(--text)] shadow-[var(--shadow-card)] backdrop-blur-sm">
              <span>
                Click <span className="text-[#7C3AED]">Generate AI content</span> to crop or trim
                in the editor
              </span>
            </span>
          </div>

          {videoAsset && (
            <p className="mt-3 flex items-center gap-1.5 text-sm text-[var(--text-3)]">
              🎥 {videoAsset.storage_key.split("/").pop()}
            </p>
          )}
        </div>

        {/* right — generate card + tip */}
        <aside className="w-full flex-none space-y-4 lg:w-[380px]">
          <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5">
            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--text-3)]">
              {processed ? "Ready to generate" : "Preparing"}
            </div>
            <h2 className="mt-1.5 text-lg font-semibold leading-snug">Turn this recording into AI content</h2>
            <p className="mt-1.5 text-sm leading-relaxed text-[var(--text-2)]">
              {wantDoc
                ? "Claude will analyze your recording and write a polished step-by-step guide."
                : "Claude will analyze your recording, clean up the narration, and produce a polished final video."}
            </p>

            {/* stats */}
            <dl className="mt-4 divide-y divide-[var(--border)] border-y border-[var(--border)] text-sm">
              {[
                ["Source length", dur ? mmss(dur) : "—"],
                ["Language", "English"],
              ].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between py-2.5">
                  <dt className="text-[var(--text-3)]">{k}</dt>
                  <dd className="font-mono font-semibold">{v}</dd>
                </div>
              ))}
            </dl>

            <button
              onClick={generate}
              disabled={generating || !videoAsset}
              className="btn btn-primary mt-4 w-full bg-gradient-to-r from-[#6d5dfb] to-[var(--brand-2)] py-3 text-[15px]"
            >
              {generating ? (
                <>
                  <Spinner /> Generating… {pct}%
                </>
              ) : (
                "✦ Generate AI content"
              )}
            </button>

            {generating && (
              <ol className="mt-4 space-y-2 border-t border-[var(--border)] pt-3">
                {STAGES.map(({ key, label }) => {
                  const st = graph ? "done" : jobFor(key)?.status;
                  return (
                    <li key={key} className="flex items-center gap-2.5 text-sm text-[var(--text-2)]">
                      <StatusDot status={st} /> {label}
                    </li>
                  );
                })}
              </ol>
            )}
          </section>

          {/* tip */}
          <section className="flex items-start gap-3 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 text-sm text-[var(--text-2)]">
            <span className="mt-0.5">💡</span>
            <span>
              Trim silent sections before generating — shorter source footage produces tighter, cleaner final videos.
            </span>
          </section>

          {error && (
            <p className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>
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
          crops={crops}
          onCancel={() => setModal(null)}
          onSave={(cs) => {
            setCrops(cs);
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
            value={voice ?? { voice_id: "af_sarah", speed: 1, use_original: false }}
            onChange={(patch) =>
              setVoice((v) => ({ ...(v ?? { voice_id: "af_sarah", speed: 1, use_original: false }), ...patch }))
            }
          />
        </ModalShell>
      )}
    </div>
  );
}
