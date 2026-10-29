"use client";

/**
 * The user's media library as its own page. It is the same per-user library the
 * editor's Media tab shows (same `useLibrary` hook, same rows), so anything
 * uploaded here appears in every project's Media tab and vice versa. Placing a
 * file into a video (full screen, overlay, music) stays in the editor — that is
 * a per-project edit; this page only manages the files themselves.
 */

import { useRef, useState } from "react";
import { mediaUrl, type LibraryAsset } from "@/lib/api";
import { fmtBytes } from "@/lib/upload";
import { EmptyState, Spinner } from "@/components/ui";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { IconLibrary, IconTrash, IconUpload } from "@/components/icons";
import { assetThumb, useLibrary } from "@/components/media/useLibrary";
import { BgCompare, CHECKER, RecordingPicker } from "@/components/media/MediaPanel";

type Filter = "all" | "image" | "video" | "audio";
const ACCEPT = "image/*,video/*,audio/*,.heic,.heif,.avif,.svg,.mkv,.flac,.opus";
const FILTER_LABEL: Record<Filter, string> = { all: "All", image: "Images", video: "Videos", audio: "Audio" };

const secs = (ms: number) => {
  const t = Math.max(0, Math.round(ms / 1000));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
};

export default function MediaLibraryPage() {
  const lib = useLibrary();
  const [filter, setFilter] = useState<Filter>("all");
  const [picking, setPicking] = useState(false);
  const [confirmDel, setConfirmDel] = useState<LibraryAsset | null>(null);
  const [compare, setCompare] = useState<LibraryAsset | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const shown = (lib.assets ?? []).filter((a) => filter === "all" || a.kind === filter);

  return (
    <main className="mx-auto w-full max-w-6xl px-8 py-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-[var(--text)]">Library</h1>
          <p className="mt-1.5 text-[15px] text-[var(--text-2)]">
            Your logos, images, clips and music. Everything here shows up in the Media tab of every project.
          </p>
        </div>
        <button onClick={() => setPicking(true)} className="btn btn-secondary">
          Reuse a recording
        </button>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (e.dataTransfer.files.length) void lib.upload(e.dataTransfer.files);
        }}
        onClick={() => fileRef.current?.click()}
        className={`mt-6 flex cursor-pointer flex-col items-center gap-1 rounded-2xl border-2 border-dashed px-4 py-8 text-center transition-colors ${dragOver ? "border-[#1E8F8E] bg-[#1E8F8E]/5" : "border-[var(--border)] hover:bg-[var(--hover)]"}`}
      >
        <IconUpload className="h-6 w-6 text-[#1E8F8E]" />
        <span className="text-sm font-medium">Upload logo, image, video or music</span>
        <span className="text-xs text-[var(--text-3)]">
          Drop files here or click · any format · videos up to 500 MB / 30 min
        </span>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) void lib.upload(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {lib.uploads.map((u) => (
        <div key={u.key} className="mt-2 rounded-lg border border-[var(--border)] px-3 py-2 text-xs">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate font-medium">{u.name}</span>
            {u.error ? (
              <button onClick={() => lib.dismissUpload(u.key)} className="text-[var(--text-3)] hover:text-[var(--text)]">
                ✕
              </button>
            ) : (
              <span className="font-mono text-[var(--text-3)]">
                {fmtBytes(u.loaded)} / {fmtBytes(u.total)}
              </span>
            )}
          </div>
          {u.error ? (
            <p className="mt-1 text-red-500">{u.error}</p>
          ) : (
            <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-[var(--bg)]">
              <div className="h-full bg-[#1E8F8E] transition-all" style={{ width: `${(u.loaded / Math.max(1, u.total)) * 100}%` }} />
            </div>
          )}
        </div>
      ))}

      <div className="mt-6 flex gap-1.5">
        {(Object.keys(FILTER_LABEL) as Filter[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${filter === f ? "bg-[#1E8F8E] text-white" : "bg-[var(--card)] text-[var(--text-2)] hover:bg-[var(--hover)]"}`}
          >
            {FILTER_LABEL[f]}
          </button>
        ))}
      </div>

      {lib.error && <p className="mt-3 text-sm text-red-500">{lib.error}</p>}
      <div className="mt-4">
        {lib.assets === null ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : shown.length === 0 ? (
          <EmptyState
            icon={<IconLibrary width={28} height={28} />}
            title={filter === "all" ? "Your library is empty" : `No ${FILTER_LABEL[filter].toLowerCase()} yet`}
            hint="Upload a file or reuse a recording to use it in any video."
          />
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {shown.map((a) => (
              <LibraryCard
                key={a.id}
                a={a}
                onCutout={() => void lib.cutout(a.id).catch(() => void lib.refresh())}
                onCompare={() => setCompare(a)}
                onDelete={() => setConfirmDel(a)}
              />
            ))}
          </div>
        )}
      </div>

      {picking && (
        <RecordingPicker
          onClose={() => setPicking(false)}
          onPick={async (r) => {
            await lib.reuse(r.session_id);
            setPicking(false);
            setFilter("video");
          }}
        />
      )}
      {compare && (
        <BgCompare a={(lib.assets ?? []).find((x) => x.id === compare.id) ?? compare} onClose={() => setCompare(null)} />
      )}
      {confirmDel && (
        <ConfirmDialog
          title="Delete from your library?"
          message={`“${confirmDel.name}” will be removed from your library. Videos that already use it render without it.`}
          onCancel={() => setConfirmDel(null)}
          onConfirm={() => {
            const id = confirmDel.id;
            setConfirmDel(null);
            void lib.remove(id);
          }}
        />
      )}
    </main>
  );
}

function LibraryCard({
  a,
  onCutout,
  onCompare,
  onDelete,
}: {
  a: LibraryAsset;
  onCutout: () => void;
  onCompare: () => void;
  onDelete: () => void;
}) {
  const thumb = assetThumb(a);
  const ready = a.status === "ready";
  return (
    <div className="card group overflow-hidden">
      <div
        className="relative flex aspect-video items-center justify-center"
        style={a.kind === "image" ? { backgroundImage: CHECKER, backgroundSize: "12px 12px" } : { background: "var(--bg)" }}
      >
        {thumb && ready ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={mediaUrl(thumb)} alt="" className="h-full w-full object-contain" draggable={false} />
        ) : a.kind === "audio" && ready ? (
          <span className="text-3xl">♪</span>
        ) : null}
        {(a.status === "processing" || a.bg_status === "running") && (
          <span className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-black/40 text-xs text-white">
            <Spinner />
            {a.bg_status === "running" ? "Removing background…" : a.source === "recording" ? "Importing…" : "Processing…"}
          </span>
        )}
        {a.duration_ms ? (
          <span className="absolute bottom-1.5 right-1.5 rounded bg-black/70 px-1 font-mono text-[11px] text-white">
            {secs(a.duration_ms)}
          </span>
        ) : null}
        <button
          onClick={onDelete}
          aria-label={`Delete ${a.name}`}
          title="Delete"
          className="absolute right-1.5 top-1.5 hidden rounded-md bg-black/60 p-1.5 text-white group-hover:block"
        >
          <IconTrash className="h-4 w-4" />
        </button>
      </div>
      <div className="p-3">
        <p className="truncate text-sm font-medium text-[var(--text)]" title={a.name}>
          {a.name}
        </p>
        <p className="mt-0.5 text-xs text-[var(--text-3)]">
          {a.kind === "image" ? "Image" : a.kind === "video" ? "Video" : "Audio"} · {fmtBytes(a.size)}
        </p>
        {a.status === "error" && <p className="mt-1 text-xs text-red-500">{a.error || "Couldn't process this file"}</p>}
        {a.kind === "image" && ready && (
          <div className="mt-2">
            {a.bg_status === "ready" ? (
              <button onClick={onCompare} className="btn btn-secondary btn-sm">
                Background removed ✓
              </button>
            ) : (
              <button onClick={onCutout} disabled={a.bg_status === "running"} className="btn btn-secondary btn-sm">
                {a.bg_status === "error" ? "Retry remove background" : "Remove background"}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
