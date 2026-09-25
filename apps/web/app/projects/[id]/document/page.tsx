"use client";

/**
 * The document page: generate → progress → editable document, with export and
 * sharing. State lives in useDocumentState; this file is the shell that picks
 * which phase to show and wires the modals.
 */

import { Suspense, use, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  downloadDocument,
  getSessionDetail,
  getVideo,
  listSessions,
  type DocExportFormat,
} from "@/lib/api";
import { DocEditor } from "@/components/doc/DocEditor";
import { DocGenerateCard } from "@/components/doc/DocGenerateCard";
import { DocProgressCard } from "@/components/doc/DocProgressCard";
import { DocView } from "@/components/doc/DocView";
import { ExportMenu } from "@/components/doc/ExportMenu";
import { RegenerateDialog } from "@/components/doc/RegenerateDialog";
import { SnapshotPicker } from "@/components/doc/SnapshotPicker";
import { useDocumentState, type SaveState } from "@/components/doc/useDocumentState";
import { ProjectAccess } from "@/components/ProjectAccess";
import { IconDoc, IconRefresh, IconVideo } from "@/components/icons";
import { Badge, Spinner } from "@/components/ui";

const SAVE_COPY: Record<SaveState, string> = {
  idle: "Saved",
  saved: "Saved",
  dirty: "Unsaved changes",
  saving: "Saving…",
  error: "Couldn't save",
};

function SaveIndicator({ state, error, onRetry }: { state: SaveState; error: string | null; onRetry: () => void }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-[12.5px] ${state === "error" ? "text-[var(--error)]" : "text-[var(--text-3)]"}`}
      title={error ?? undefined}
      aria-live="polite"
    >
      {state === "saving" && <Spinner className="h-3 w-3" />}
      {SAVE_COPY[state]}
      {state === "error" && (
        <button type="button" onClick={onRetry} className="underline">
          Retry
        </button>
      )}
    </span>
  );
}

function DocumentPageInner({ id }: { id: string }) {
  const router = useRouter();
  const autogen = useSearchParams().get("autogen") === "1";
  const s = useDocumentState(id);
  const [regen, setRegen] = useState(false);
  const [pickStep, setPickStep] = useState<string | null>(null);
  const [source, setSource] = useState<string | null | undefined>(undefined); // undefined = not looked up yet
  const [notice, setNotice] = useState<string | null>(null);
  const autogenFired = useRef(false);

  // "Generate document" from the project page lands here with ?autogen=1
  useEffect(() => {
    if (autogen && s.phase === "none" && !autogenFired.current) {
      autogenFired.current = true;
      void s.generate({});
    }
  }, [autogen, s.phase, s]);

  // The source video key, resolved lazily (only needed to pick frames).
  const resolveSource = useCallback(async () => {
    if (source !== undefined) return source;
    let key: string | null = null;
    try {
      const v = await getVideo(id);
      key = v?.source_proxy ?? v?.source_video ?? null;
      if (!key) {
        const sessions = await listSessions(id);
        const newest = [...sessions].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))[0];
        if (newest) {
          const detail = await getSessionDetail(newest.id);
          key =
            (detail.assets.find((a) => a.kind === "proxy") ?? detail.assets.find((a) => a.kind === "raw_video"))
              ?.storage_key ?? null;
        }
      }
    } catch {
      key = null;
    }
    setSource(key);
    return key;
  }, [id, source]);

  useEffect(() => {
    if (s.phase === "ready") void resolveSource();
  }, [s.phase, resolveSource]);

  const navigate = async (e: React.MouseEvent, href: string) => {
    if (!s.dirty) return;
    e.preventDefault();
    await s.flush();
    router.push(href);
  };

  const exportDoc = async (format: DocExportFormat) => {
    await s.flush();
    const name = (s.doc?.title ?? "document").replace(/[^a-z0-9]+/gi, "-").toLowerCase();
    try {
      await downloadDocument(id, format, `${name}.${format}`);
    } catch (e) {
      setNotice(String(e instanceof Error ? e.message : e));
    }
  };

  const pickingStep = pickStep ? s.doc?.steps.find((x) => x.id === pickStep) : undefined;
  const pickingIndex = pickStep ? (s.doc?.steps.findIndex((x) => x.id === pickStep) ?? -1) : -1;

  return (
    <main className="mx-auto max-w-3xl px-4 py-6 sm:px-6 sm:py-10">
      {regen && (
        <RegenerateDialog
          initial={s.lastOpts}
          onCancel={() => setRegen(false)}
          onConfirm={(opts) => {
            setRegen(false);
            void s.generate(opts);
          }}
        />
      )}
      {pickingStep && source && (
        <SnapshotPicker
          source={source}
          step={pickingStep}
          stepIndex={pickingIndex}
          onCancel={() => setPickStep(null)}
          onPick={(t) => {
            const stepId = pickingStep.id;
            setPickStep(null);
            s.changeSnapshot(stepId, t).catch((e) => setNotice(String(e instanceof Error ? e.message : e)));
          }}
        />
      )}

      <Link href={`/projects/${id}`} onClick={(e) => void navigate(e, `/projects/${id}`)} className="btn btn-ghost btn-sm -ml-2">
        ← Project
      </Link>

      {/* Video ⇄ Document toggle + actions */}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-lg border border-[var(--border)] bg-[var(--card)] p-1">
          <Link
            href={`/projects/${id}/video`}
            onClick={(e) => void navigate(e, `/projects/${id}/video`)}
            className="btn btn-ghost btn-sm gap-1.5"
          >
            <IconVideo width={15} height={15} /> Video
          </Link>
          <span className="btn btn-sm gap-1.5 bg-[var(--navy)] text-white">
            <IconDoc width={15} height={15} /> Document
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {s.phase === "ready" && <SaveIndicator state={s.saveState} error={s.saveError} onRetry={() => void s.save()} />}
          {s.phase === "ready" && (
            <button type="button" onClick={() => setRegen(true)} className="btn btn-secondary btn-sm gap-1.5">
              <IconRefresh width={14} height={14} /> Regenerate
            </button>
          )}
          {s.phase === "ready" && <ExportMenu onExport={exportDoc} />}
          <ProjectAccess projectId={id} kind="doc" />
        </div>
      </div>

      {s.state?.stale && s.phase === "ready" && (
        <p className="mt-4 flex flex-wrap items-center gap-2 text-[13px] text-[var(--text-2)]">
          <Badge tone="amber">Recording reprocessed</Badge>
          The workflow was re-analysed after this document was written. Regenerate to pick up the changes.
        </p>
      )}
      {notice && (
        <p className="mt-4 flex items-center justify-between gap-3 rounded-lg border border-[#D9534F]/30 bg-[#D9534F]/10 px-3 py-2 text-sm text-[var(--error)]">
          {notice}
          <button type="button" onClick={() => setNotice(null)} className="underline">
            Dismiss
          </button>
        </p>
      )}

      <div className="mt-6">
        {s.phase === "loading" && (
          <div className="flex justify-center py-16 text-[var(--text-3)]">
            <Spinner />
          </div>
        )}
        {s.phase === "none" && <DocGenerateCard onGenerate={(o) => void s.generate(o)} error={s.serverError} />}
        {(s.phase === "queued" || s.phase === "running") && <DocProgressCard phase={s.phase} projectId={id} progress={s.state?.progress} message={s.state?.message} />}
        {s.phase === "error" && (
          <section className="card mx-auto max-w-2xl p-6 sm:p-8">
            <h2 className="text-[18px] font-semibold text-[var(--text)]">Generation failed</h2>
            <p className="mt-2 text-[14px] text-[var(--text-2)]">{s.serverError ?? "Something went wrong."}</p>
            <div className="mt-5 flex flex-wrap gap-2">
              <button type="button" onClick={() => void s.generate(s.lastOpts)} className="btn btn-primary">
                Try again
              </button>
              {s.state?.doc && (
                <button type="button" onClick={s.openLastVersion} className="btn btn-secondary">
                  Open last version
                </button>
              )}
            </div>
          </section>
        )}
        {s.phase === "ready" && s.doc && (
          <DocEditor
            doc={s.doc}
            onChange={s.edit}
            onChangeFrame={(stepId) => {
              void resolveSource().then((key) => (key ? setPickStep(stepId) : setNotice("No source video for this project.")));
            }}
            onRemoveSnapshot={s.removeSnapshot}
            snapshotBusy={s.snapshotBusy}
            canPickFrames={source !== null}
          />
        )}
        {s.phase === "ready" && !s.doc && s.state?.doc && <DocView doc={s.state.doc} />}
      </div>
    </main>
  );
}

export default function DocumentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <Suspense fallback={null}>
      <DocumentPageInner id={id} />
    </Suspense>
  );
}
