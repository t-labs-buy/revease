"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  downloadDocument,
  getDocument,
  mediaUrl,
  regenerateDocument,
  type SopDoc,
} from "@/lib/api";
import { IconDoc, IconVideo } from "@/components/icons";
import { ShareButton } from "@/components/ShareButton";

export default function DocumentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [doc, setDoc] = useState<SopDoc | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState<"md" | "pdf" | null>(null);

  const exportDoc = async (format: "md" | "pdf") => {
    setExporting(format);
    try {
      const name = (doc?.title ?? "document").replace(/[^a-z0-9]+/gi, "-").toLowerCase();
      await downloadDocument(id, format, `${name}.${format}`);
    } catch (e) {
      setError(String(e));
    } finally {
      setExporting(null);
    }
  };

  const load = useCallback(async () => {
    try {
      const r = await getDocument(id);
      setDoc(r?.doc ?? null);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <Link href={`/projects/${id}`} className="btn btn-ghost btn-sm -ml-2">
        ← Project
      </Link>

      {/* Video ⇄ Document toggle */}
      <div className="mt-3 flex items-center justify-between gap-3">
        <div className="inline-flex rounded-xl border border-zinc-800/70 bg-zinc-900/40 p-1">
          <Link href={`/projects/${id}/video`} className="btn btn-ghost btn-sm gap-1.5">
            <IconVideo width={15} height={15} /> Video
          </Link>
          <span className="btn btn-sm gap-1.5 bg-zinc-800 text-[var(--text)]">
            <IconDoc width={15} height={15} /> Document
          </span>
        </div>
        <div className="flex gap-2">
          <button
            onClick={async () => {
              setBusy(true);
              try {
                const r = await regenerateDocument(id);
                setDoc(r.doc);
              } catch (e) {
                setError(String(e));
              } finally {
                setBusy(false);
              }
            }}
            className="btn btn-secondary btn-sm"
          >
            {busy ? "…" : "Regenerate"}
          </button>
          {/* Export is an authenticated route, so download via fetch rather than
              a bare <a href>, which the browser would send without the token. */}
          <button
            onClick={() => void exportDoc("md")}
            disabled={exporting !== null}
            className="btn btn-secondary btn-sm"
          >
            {exporting === "md" ? "…" : "Markdown"}
          </button>
          <button
            onClick={() => void exportDoc("pdf")}
            disabled={exporting !== null}
            className="btn btn-primary btn-sm"
          >
            {exporting === "pdf" ? "…" : "PDF"}
          </button>
          <ShareButton projectId={id} kind="doc" />
        </div>
      </div>

      {error && (
        <p className="mt-4 rounded-lg border border-red-900/60 bg-red-950/30 px-3 py-2 text-sm text-red-300">
          {error}
        </p>
      )}

      {!doc && !error && (
        <p className="mt-8 text-sm text-zinc-500">
          No document yet — process a capture into a Workflow Graph first.
        </p>
      )}

      {doc && (
        <article className="mt-6">
          <h1 className="text-3xl font-semibold tracking-tight">{doc.title}</h1>
          <p className="mt-2 text-zinc-500">{doc.summary}</p>

          <ol className="mt-8 space-y-8">
            {doc.steps.map((s) => (
              <li key={s.n} className="border-l-2 border-zinc-800 pl-5">
                <div className="flex items-center gap-2">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-violet-600 text-xs font-semibold text-[var(--text)]">
                    {s.n}
                  </span>
                  <h2 className="text-lg font-medium text-zinc-100">{s.title}</h2>
                </div>
                {s.body && <p className="mt-2 text-zinc-300">{s.body}</p>}
                {s.screenshot && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={mediaUrl(s.screenshot)}
                    alt={`Step ${s.n}`}
                    className="mt-3 w-full rounded-lg border border-zinc-800"
                  />
                )}
              </li>
            ))}
          </ol>
        </article>
      )}
    </main>
  );
}
