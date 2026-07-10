"use client";

import { Suspense, use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  estimateOutputMs,
  getGraph,
  getSessionDetail,
  getSessionStatus,
  getVideo,
  mediaUrl,
  reprocessSession,
  type EditSpec,
  type GraphRow,
  type SessionDetail,
  type SessionStatus,
} from "@/lib/api";
import { Badge, StatusDot } from "@/components/ui";

// One "AI Generate" flow — the real pipeline jobs shown as friendly stages.
const AI_STAGES = [
  { key: "media", label: "Analyzing footage" },
  { key: "whisper", label: "AI voice from your narration" },
  { key: "merge", label: "Speed-up & zoom on the action" },
  { key: "extract", label: "Composing your video" },
];

const fmt = (ms: number) => {
  const s = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
};

export default function SessionPage({
  params,
}: {
  params: Promise<{ id: string; sid: string }>;
}) {
  return (
    <Suspense fallback={null}>
      <SessionPageInner params={params} />
    </Suspense>
  );
}

function SessionPageInner({ params }: { params: Promise<{ id: string; sid: string }> }) {
  const { id, sid } = use(params);
  const router = useRouter();
  const next = useSearchParams().get("next"); // "video" | "doc" — auto-open when ready
  const redirected = useRef(false);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [status, setStatus] = useState<SessionStatus | null>(null);
  const [graph, setGraph] = useState<GraphRow | null>(null);
  const [spec, setSpec] = useState<EditSpec | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [autoGen, setAutoGen] = useState(false); // user clicked AI Generate -> open editor when ready

  const refresh = useCallback(async () => {
    try {
      const [d, st, g] = await Promise.all([
        getSessionDetail(sid),
        getSessionStatus(sid),
        getGraph(id),
      ]);
      setDetail(d);
      setStatus(st);
      setGraph(g);
      if (g) getVideo(id).then((v) => setSpec(v?.edit_spec ?? null)).catch(() => {});
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [id, sid]);

  useEffect(() => {
    void refresh();
    // full refresh while processing so the graph appears (and auto-redirect fires)
    const iv = setInterval(() => void refresh(), 2500);
    return () => clearInterval(iv);
  }, [refresh]);

  // once the graph is ready, auto-open the editor (video) or document (doc) —
  // either because we arrived with ?next=, or the user clicked AI Generate.
  useEffect(() => {
    if (redirected.current || !graph) return;
    if (next === "doc") {
      redirected.current = true;
      router.replace(`/projects/${id}/document`);
    } else if (next === "video" || autoGen) {
      redirected.current = true;
      router.replace(`/projects/${id}/video`);
    }
  }, [next, autoGen, graph, id, router]);

  const videoAsset = detail?.assets.find((a) => a.kind === "raw_video");
  const jobFor = (stage: string) => status?.jobs.find((j) => j.stage === stage);

  const processing = status?.status === "processing" || status?.status === "captured";

  // Single "AI Generate": open the editor if ready; otherwise start/track the
  // pipeline and auto-open when it finishes.
  function aiGenerate() {
    if (graph) {
      router.replace(`/projects/${id}/video`);
      return;
    }
    setAutoGen(true);
    if (!processing) reprocessSession(sid).then(refresh).catch((e) => setError(String(e)));
  }

  const doneStages = AI_STAGES.filter((s) => jobFor(s.key)?.status === "done").length;
  const anyError = AI_STAGES.some((s) => jobFor(s.key)?.status === "error");
  const pct = graph ? 100 : Math.round((doneStages / AI_STAGES.length) * 100);

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <Link href={`/projects/${id}`} className="btn btn-ghost btn-sm -ml-2">
        ← Project
      </Link>

      <div className="mt-3">
        <h1 className="text-2xl font-semibold tracking-tight">Session</h1>
        <p className="mt-0.5 flex items-center gap-2 text-sm text-zinc-500">
          {detail?.source_type}
          {status && (
            <Badge tone={status.status === "ready" ? "green" : processing ? "amber" : "zinc"}>
              {status.status}
              {status.latest_version ? ` · v${status.latest_version}` : ""}
            </Badge>
          )}
        </p>
      </div>

      {error && (
        <p className="mt-4 rounded-lg border border-red-900/60 bg-red-950/30 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      {next && !graph && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-violet-500/30 bg-violet-500/10 px-3 py-2 text-sm text-violet-200">
          <StatusDot status="running" />
          Preparing your {next === "doc" ? "document" : "video"} — this opens automatically when
          processing finishes.
        </div>
      )}

      <div className="mt-6 grid gap-4 lg:grid-cols-5">
        {/* left: video */}
        {videoAsset && (
          <section className="card overflow-hidden lg:col-span-3">
            <div className="border-b border-zinc-800/60 px-4 py-3">
              <div className="label">Original recording</div>
            </div>
            <video
              src={mediaUrl(videoAsset.storage_key)}
              poster={detail?.poster ? mediaUrl(detail.poster) : undefined}
              controls
              className="aspect-video w-full bg-black"
            />
          </section>
        )}

        {/* right: single AI Generate flow */}
        <div className={`grid gap-4 ${videoAsset ? "lg:col-span-2" : "lg:col-span-5"}`}>
          <section className="card bg-gradient-to-br from-violet-600/10 to-transparent p-5">
            <div className="label mb-1">AI Generate</div>
            <p className="text-sm text-zinc-400">
              One pass — speed up the idle parts, zoom on the action, and add an AI voiceover
              from your narration.
            </p>

            {/* progress bar */}
            <div className="mt-4">
              <div className="mb-1 flex items-center justify-between text-xs text-zinc-500">
                <span>{graph ? "Ready" : anyError ? "Needs attention" : "Generating…"}</span>
                <span>{pct}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-zinc-800">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    anyError ? "bg-red-500" : "bg-violet-500"
                  }`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>

            {/* staged checklist */}
            <ol className="mt-4 space-y-2.5">
              {AI_STAGES.map(({ key, label }) => {
                const st = graph ? "done" : jobFor(key)?.status;
                return (
                  <li key={key} className="flex items-center gap-3 text-sm">
                    <StatusDot status={st} />
                    <span className="flex-1 text-zinc-300">{label}</span>
                    <span className="text-xs text-zinc-500">
                      {st === "running" ? "…" : st === "done" ? "✓" : st === "error" ? "!" : ""}
                    </span>
                  </li>
                );
              })}
            </ol>

            {graph && spec ? (
              <>
                <div className="mt-4 text-xs text-zinc-500">
                  ≈ {fmt(estimateOutputMs(spec))} · {spec.segments.length} scenes · AI voiceover
                  {spec.captions.enabled ? " + captions" : ""}
                </div>
                <button onClick={aiGenerate} className="btn btn-primary mt-3 w-full">
                  Open editor →
                </button>
                <Link
                  href={`/projects/${id}/document`}
                  className="btn btn-ghost btn-sm mt-1 w-full"
                >
                  or generate a document
                </Link>
              </>
            ) : (
              <>
                <button
                  onClick={aiGenerate}
                  disabled={autoGen && processing}
                  className="btn btn-primary mt-4 w-full"
                >
                  {autoGen && processing ? (
                    <>
                      <StatusDot status="running" /> Generating…
                    </>
                  ) : (
                    "AI Generate video"
                  )}
                </button>
                {autoGen && (
                  <p className="mt-2 text-center text-xs text-zinc-500">
                    Opens the editor automatically when it&apos;s ready.
                  </p>
                )}
              </>
            )}
          </section>
        </div>
      </div>

      {/* Workflow graph */}
      <section className="mt-10">
        <div className="mb-3 flex items-center justify-between">
          <div className="label">
            Workflow Graph {graph ? `· ${graph.graph_json.steps.length} steps` : ""}
          </div>
        </div>
        {!graph ? (
          <div className="card flex items-center gap-3 p-5 text-sm text-zinc-500">
            {processing && <StatusDot status="running" />}
            {processing
              ? "Processing — steps will appear here when the pipeline finishes."
              : "No graph yet. Needs the Celery worker + Redis running."}
          </div>
        ) : (
          <ol className="grid gap-2.5">
            {graph.graph_json.steps.slice(0, 60).map((s, i) => (
              <li key={s.id} className="card flex gap-3 p-3">
                {s.screenshot ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={mediaUrl(s.screenshot)}
                    alt={s.target}
                    className="h-16 w-28 flex-none rounded-lg object-cover ring-1 ring-zinc-800"
                  />
                ) : (
                  <div className="flex h-16 w-28 flex-none items-center justify-center rounded-lg bg-zinc-800/50 text-xs text-zinc-600">
                    no shot
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-sm font-medium text-zinc-100">
                    <span className="flex h-5 w-5 items-center justify-center rounded bg-zinc-800 text-[11px] text-zinc-400">
                      {i + 1}
                    </span>
                    {s.action} — {s.target}
                  </div>
                  {s.narration && (
                    <div className="mt-1 line-clamp-2 text-sm text-zinc-400">{s.narration}</div>
                  )}
                  <div className="mt-1 text-xs text-zinc-600">
                    {s.t_start != null ? `${s.t_start?.toFixed?.(1)}s–${s.t_end?.toFixed?.(1)}s` : ""}
                  </div>
                </div>
              </li>
            ))}
          </ol>
        )}
        {graph && graph.graph_json.steps.length > 60 && (
          <p className="mt-2 text-xs text-zinc-600">
            …and {graph.graph_json.steps.length - 60} more.
          </p>
        )}
      </section>
    </main>
  );
}
