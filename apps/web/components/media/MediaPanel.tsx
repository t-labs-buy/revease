"use client";

/**
 * Editor Media tab (replaces the old Intro tab). Three parts:
 *
 *  1. Library — the user's logos, images, clips and music, reusable in every
 *     project; upload any format, or reuse a recording from another project.
 *  2. In this video — what the library placed here:
 *       inserts  = full-screen clips / stills / title cards between scenes
 *                  (Start is the intro, End the outro; the recording pauses)
 *       overlays = logos / picture-in-picture over the video, dragged into
 *                  place on the preview, shown for the whole video, the scenes
 *                  only, or a custom time range
 *  3. Music — a library track under the narration, ducked while someone
 *     speaks. No track chosen = no music (the old synthesized pad is gone).
 *
 * Everything here only edits the spec; the renderer places inserts between
 * scene clips and composites overlays at concat, so none of it re-renders a
 * scene (see worker/pipeline/placement.py).
 */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  effectiveInserts,
  insertDurationMs,
  listReusableRecordings,
  mediaUrl,
  type EditSegment,
  type EditSpec,
  type InsertPosition,
  type LibraryAsset,
  type MediaInsert,
  type MediaOverlay,
  type MusicSettings,
  type OverlayRange,
  type ReusableRecording,
} from "@/lib/api";
import { fmtBytes } from "@/lib/upload";
import { Spinner } from "@/components/ui";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ModalShell } from "@/components/EditModals";
import { IconTrash, IconUpload } from "@/components/icons";
import { assetKey, assetThumb, useLibrary } from "@/components/media/useLibrary";
import { MUSIC_AUDITION_EVENT } from "@/components/media/MediaOverlayLayer";

type Filter = "all" | "image" | "video" | "audio";

const ASPECT: Record<string, number> = { "16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1 };
// Section headings: the shared `eyebrow` (11px, muted grey) got lost between
// the cards on this tab, so these are a step bigger, bold and full-contrast.
const heading = "text-xs font-bold uppercase tracking-[0.08em] text-[var(--text)]";
const ACCEPT = "image/*,video/*,audio/*,.heic,.heif,.avif,.svg,.mkv,.flac,.opus";

const secs = (ms: number | null | undefined) => {
  const t = Math.max(0, Math.round((ms ?? 0) / 1000));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
};
const uid = () => Math.random().toString(36).slice(2, 10);
const sceneLabel = (s: EditSegment, i: number) => {
  const text = (s.target || s.words.filter((_, k) => !s.removed.includes(k)).join(" ") || "scene").trim();
  return `${i + 1}. ${text.length > 34 ? `${text.slice(0, 33)}…` : text}`;
};

export function MediaPanel({
  spec,
  patchSpec,
  curMs,
  totalMs,
  selOverlay,
  setSelOverlay,
}: {
  spec: EditSpec;
  patchSpec: (p: Partial<EditSpec>) => void;
  curMs: number;
  totalMs: number;
  selOverlay: string | null;
  setSelOverlay: (id: string | null) => void;
}) {
  const lib = useLibrary();
  const [filter, setFilter] = useState<Filter>("all");
  const [picking, setPicking] = useState(false);
  const [confirmDel, setConfirmDel] = useState<LibraryAsset | null>(null);
  const [compare, setCompare] = useState<LibraryAsset | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const inserts = spec.inserts ?? [];
  const overlays = spec.overlays ?? [];
  const music: MusicSettings = spec.music ?? { enabled: false, storage_key: null, gain_db: -18 };
  const byId = useMemo(() => new Map((lib.assets ?? []).map((a) => [a.id, a])), [lib.assets]);

  // Projects saved with the old Intro tab: fold enabled intro/outro cards into
  // inserts once, so they show (and can be edited) here. Renders are identical
  // either way — the server folds them the same way (editspec.effective_inserts).
  const migrated = useRef(false);
  useEffect(() => {
    if (migrated.current) return;
    migrated.current = true;
    const legacy = effectiveInserts(spec).filter((x) => x.legacy);
    if (!legacy.length) return;
    const clean = legacy.map(({ slot: _slot, legacy: _legacy, ...it }) => it as MediaInsert);
    patchSpec({
      inserts: [...clean.filter((x) => x.position === "start"), ...inserts, ...clean.filter((x) => x.position !== "start")],
      intro: { ...spec.intro, enabled: false },
      outro: { ...spec.outro, enabled: false },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // the scene at the playhead — new inserts go right after it
  const sceneAt = useMemo(() => {
    const segs = spec.segments;
    let idx = 0;
    segs.forEach((s, i) => {
      if (s.source_start_ms <= curMs) idx = i;
    });
    return segs[idx];
  }, [spec.segments, curMs]);

  const setInserts = (next: MediaInsert[]) => patchSpec({ inserts: next });
  const setOverlays = (next: MediaOverlay[]) => patchSpec({ overlays: next });
  const patchInsert = (id: string, p: Partial<MediaInsert>) =>
    setInserts(inserts.map((x) => (x.id === id ? { ...x, ...p } : x)));
  const patchOverlay = (id: string, p: Partial<MediaOverlay>) =>
    setOverlays(overlays.map((x) => (x.id === id ? { ...x, ...p } : x)));

  function addInsert(a: LibraryAsset) {
    const key = assetKey(a);
    if (!key) return;
    const it: MediaInsert = {
      id: uid(),
      type: a.kind === "video" ? "video" : "image",
      asset_id: a.id,
      media_key: key,
      name: a.name,
      position: sceneAt ? `after:${sceneAt.step_id}` : "start",
      duration_ms: a.kind === "video" ? a.duration_ms || 3000 : 3000,
      media_ms: a.duration_ms ?? undefined,
      keep_audio: a.kind === "video" ? a.has_audio : undefined,
      fit: a.kind === "image" ? "contain" : "cover",
    };
    setInserts([...inserts, it]);
  }

  function addOverlay(a: LibraryAsset) {
    const nobg = a.kind === "image" && !!a.nobg_key;
    const key = assetKey(a, nobg);
    if (!key) return;
    const frameAspect = ASPECT[spec.aspect] ?? 16 / 9;
    const mediaAspect = a.width && a.height ? a.width / a.height : 16 / 9;
    const w = a.kind === "video" ? 0.3 : 0.16;
    const h = Math.min(0.9, (w * frameAspect) / mediaAspect);
    const range: OverlayRange =
      a.kind === "video"
        ? { start_ms: Math.round(curMs), end_ms: Math.round(Math.min(totalMs, curMs + (a.duration_ms || 5000))) }
        : "all";
    const ov: MediaOverlay = {
      id: uid(),
      type: a.kind === "video" ? "video" : "image",
      asset_id: a.id,
      media_key: key,
      name: a.name,
      nobg,
      x: 1 - w - 0.03,
      y: a.kind === "video" ? 1 - h - 0.04 : 0.04,
      w,
      h,
      range,
      opacity: 1,
      loop: true,
    };
    setOverlays([...overlays, ov]);
    setSelOverlay(ov.id);
  }

  function useAsMusic(a: LibraryAsset) {
    const key = assetKey(a);
    if (!key) return;
    patchSpec({
      music: {
        ...music,
        enabled: true,
        storage_key: key,
        asset_id: a.id,
        name: a.name,
        duck: music.duck ?? true,
        fade_in_ms: music.fade_in_ms ?? 1000,
        fade_out_ms: music.fade_out_ms ?? 2000,
        start_ms: 0,
      },
    });
  }

  function addTitleCard() {
    setInserts([
      ...inserts,
      { id: uid(), type: "title", title: spec.title || "Title", position: "start", duration_ms: 2000 },
    ]);
  }

  const shown = (lib.assets ?? []).filter((a) => filter === "all" || a.kind === filter);
  const ordered = effectiveInserts({ ...spec, inserts, intro: { ...spec.intro, enabled: false }, outro: { ...spec.outro, enabled: false } });

  return (
    <div className="space-y-6">
      <p className="text-xs text-[var(--text-3)]">
        Add logos, images, clips and music from your library. Put them full-screen between scenes (start = intro,
        end = outro) or on top of the video — drag overlays into place on the preview.
      </p>

      {/* ---------------- library ---------------- */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className={heading}>My media</h3>
          <button onClick={() => setPicking(true)} className="text-xs font-medium text-[#1E8F8E] hover:underline">
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
          className={`flex cursor-pointer flex-col items-center gap-1 rounded-xl border-2 border-dashed px-3 py-4 text-center transition-colors ${dragOver ? "border-[#1E8F8E] bg-[#1E8F8E]/5" : "border-[var(--border)] hover:bg-[var(--hover)]"}`}
        >
          <IconUpload className="h-5 w-5 text-[#1E8F8E]" />
          <span className="text-sm font-medium">Upload logo, image, video or music</span>
          <span className="text-[11px] text-[var(--text-3)]">Any format — PNG, JPG, SVG, HEIC, MP4, MOV, WebM, MP3, WAV… · videos up to 500 MB / 30 min</span>
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

        <div className="mt-3 flex gap-1.5">
          {(["all", "image", "video", "audio"] as Filter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${filter === f ? "bg-[#1E8F8E] text-white" : "bg-[var(--bg)] text-[var(--text-2)] hover:bg-[var(--hover)]"}`}
            >
              {{ all: "All", image: "Images", video: "Videos", audio: "Audio" }[f]}
            </button>
          ))}
        </div>

        {lib.error && <p className="mt-2 text-xs text-red-500">{lib.error}</p>}
        {lib.assets === null ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : shown.length === 0 ? (
          <p className="mt-3 text-xs text-[var(--text-3)]">
            {filter === "all" ? "Nothing here yet — upload a file or reuse a recording." : "No files of this type yet."}
          </p>
        ) : (
          <div className="mt-3 grid grid-cols-2 gap-2">
            {shown.map((a) => (
              <AssetCard
                key={a.id}
                a={a}
                onInsert={() => addInsert(a)}
                onOverlay={() => addOverlay(a)}
                onMusic={() => useAsMusic(a)}
                onCutout={() => void lib.cutout(a.id).catch(() => void lib.refresh())}
                onCompare={() => setCompare(a)}
                onDelete={() => setConfirmDel(a)}
                isMusic={music.enabled && music.asset_id === a.id}
              />
            ))}
          </div>
        )}
      </section>

      {/* ---------------- in this video ---------------- */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className={heading}>Between scenes</h3>
          <button onClick={addTitleCard} className="text-xs font-medium text-[#1E8F8E] hover:underline">
            + Title card
          </button>
        </div>
        {ordered.length === 0 ? (
          <p className="text-xs text-[var(--text-3)]">
            Nothing inserted. Use <b>Full screen</b> on a file to play it before, between or after scenes.
          </p>
        ) : (
          <ul className="space-y-5">
            {ordered.map((it) => (
              <InsertRow
                key={it.id}
                it={it}
                segments={spec.segments}
                asset={it.asset_id ? byId.get(it.asset_id) : undefined}
                onPatch={(p) => patchInsert(it.id, p)}
                onRemove={() => setInserts(inserts.filter((x) => x.id !== it.id))}
              />
            ))}
          </ul>
        )}
        {ordered.length > 0 && (
          <p className="mt-2 text-[11px] text-[var(--text-3)]">Inserted clips play in the exported video; the preview shows only the recording.</p>
        )}
      </section>

      <section>
        <h3 className={`${heading} mb-2`}>On top of the video</h3>
        {overlays.length === 0 ? (
          <p className="text-xs text-[var(--text-3)]">
            No overlays. Use <b>Overlay</b> on a logo or <b>Picture-in-picture</b> on a clip.
          </p>
        ) : (
          <ul className="space-y-2">
            {overlays.map((ov) => (
              <OverlayRow
                key={ov.id}
                ov={ov}
                asset={byId.get(ov.asset_id)}
                selected={selOverlay === ov.id}
                onSelect={() => setSelOverlay(ov.id)}
                curMs={curMs}
                totalMs={totalMs}
                onPatch={(p) => patchOverlay(ov.id, p)}
                onCutout={() => void lib.cutout(ov.asset_id).catch(() => void lib.refresh())}
                onRemove={() => {
                  setOverlays(overlays.filter((x) => x.id !== ov.id));
                  if (selOverlay === ov.id) setSelOverlay(null);
                }}
              />
            ))}
          </ul>
        )}
      </section>

      {/* the whole section waits for a track: "Use as music" on an audio file
          above is what brings it in (that sets the track and turns music on) */}
      {music.storage_key && (
        <MusicSection music={music} asset={music.asset_id ? byId.get(music.asset_id) : undefined} patchSpec={patchSpec} />
      )}

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
      {compare && <BgCompare a={byId.get(compare.id) ?? compare} onClose={() => setCompare(null)} />}
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
    </div>
  );
}

/* ------------------------------------------------------------------ */

function AssetCard({
  a,
  onInsert,
  onOverlay,
  onMusic,
  onCutout,
  onCompare,
  onDelete,
  isMusic,
}: {
  a: LibraryAsset;
  onInsert: () => void;
  onOverlay: () => void;
  onMusic: () => void;
  onCutout: () => void;
  onCompare: () => void;
  onDelete: () => void;
  isMusic: boolean;
}) {
  const thumb = assetThumb(a);
  const ready = a.status === "ready";
  // The card's actions are small bold pills in the brand colour — as plain grey
  // text they read as captions, and nobody realised "Full screen" was a button.
  const act =
    "rounded-md border border-[#1E8F8E]/30 bg-[#1E8F8E]/5 px-2 py-1 text-[11px] font-semibold text-[#1E8F8E] " +
    "hover:border-[#1E8F8E] hover:bg-[#1E8F8E]/15 disabled:opacity-40 disabled:hover:border-[#1E8F8E]/30 disabled:hover:bg-[#1E8F8E]/5";
  return (
    <div className="group overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]">
      <div
        className="relative flex aspect-video items-center justify-center"
        style={a.kind === "image" ? { backgroundImage: CHECKER, backgroundSize: "12px 12px" } : { background: "var(--bg)" }}
      >
        {thumb && ready ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={mediaUrl(thumb)} alt="" className="h-full w-full object-contain" draggable={false} />
        ) : a.kind === "audio" && ready ? (
          <span className="text-2xl">♪</span>
        ) : null}
        {a.status === "processing" && (
          <span className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-black/40 text-[10px] text-white">
            <Spinner />
            {a.source === "recording" ? "Importing…" : "Processing…"}
          </span>
        )}
        {a.bg_status === "running" && (
          <span className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-black/40 text-[10px] text-white">
            <Spinner />
            Removing background…
          </span>
        )}
        {a.duration_ms ? (
          <span className="absolute bottom-1 right-1 rounded bg-black/70 px-1 font-mono text-[10px] text-white">{secs(a.duration_ms)}</span>
        ) : null}
        <button
          onClick={onDelete}
          aria-label={`Delete ${a.name}`}
          className="absolute right-1 top-1 hidden rounded-md bg-black/60 p-1 text-white group-hover:block"
        >
          <IconTrash className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="px-2 pb-1.5 pt-1">
        <p className="truncate text-[11px] font-medium" title={a.name}>
          {a.name}
        </p>
        {a.status === "error" ? (
          <p className="text-[10px] text-red-500">{a.error || "Couldn't process this file"}</p>
        ) : (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {a.kind === "image" && (
              <>
                <button disabled={!ready} onClick={onOverlay} className={act}>Overlay</button>
                <button disabled={!ready} onClick={onInsert} className={act}>Full screen</button>
                {a.bg_status === "ready" ? (
                  <button onClick={onCompare} className={act}>BG removed ✓</button>
                ) : (
                  <button disabled={!ready || a.bg_status === "running"} onClick={onCutout} className={act}>
                    {a.bg_status === "error" ? "Retry remove BG" : "Remove BG"}
                  </button>
                )}
              </>
            )}
            {a.kind === "video" && (
              <>
                <button disabled={!ready} onClick={onInsert} className={act}>Full screen</button>
                <button disabled={!ready} onClick={onOverlay} className={act}>Picture-in-picture</button>
              </>
            )}
            {a.kind === "audio" && (
              <button disabled={!ready || isMusic} onClick={onMusic} className={act}>
                {isMusic ? "Music ✓" : "Use as music"}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

const CHECKER =
  "linear-gradient(45deg,#8883 25%,transparent 25%),linear-gradient(-45deg,#8883 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#8883 75%),linear-gradient(-45deg,transparent 75%,#8883 75%)";

/* ------------------------------------------------------------------ */

function InsertRow({
  it,
  segments,
  asset,
  onPatch,
  onRemove,
}: {
  it: MediaInsert;
  segments: EditSegment[];
  asset?: LibraryAsset;
  onPatch: (p: Partial<MediaInsert>) => void;
  onRemove: () => void;
}) {
  const mediaMs = it.media_ms ?? asset?.duration_ms ?? undefined;
  const icon = it.type === "title" ? "T" : it.type === "video" ? "▶" : "▣";
  const posValid = it.position === "start" || it.position === "end" || segments.some((s) => `after:${s.step_id}` === it.position);
  // A settings card, not a form row: thumbnail + name + a plain-words line
  // saying what this is, then every setting on its own labelled line with a
  // fixed label column. Two earlier layouts (a bare label/field grid, then
  // everything inline on two lines) both read as a wall of controls.
  const thumb = asset ? assetThumb(asset) : null;
  const kindLine =
    it.type === "title"
      ? "Title card · full screen"
      : it.type === "video"
        ? "Video clip · plays full screen, the recording pauses"
        : "Image · shows full screen, the recording pauses";
  const row = "grid grid-cols-[6.5rem_1fr] items-center gap-x-3";
  const lbl = "text-xs text-[var(--text-3)]";
  return (
    <li className="rounded-xl border-2 border-[#1E8F8E]/35 bg-[var(--card)] p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <span className="flex h-11 w-[4.5rem] flex-none items-center justify-center overflow-hidden rounded-md bg-[var(--bg)] text-sm font-semibold text-[#1E8F8E]">
          {thumb ? <img src={mediaUrl(thumb)} alt="" className="h-full w-full object-cover" draggable={false} /> : icon}
        </span>
        <div className="min-w-0 flex-1">
          {it.type === "title" ? (
            <input
              value={it.title ?? ""}
              onChange={(e) => onPatch({ title: e.target.value })}
              placeholder="Title text"
              className="input h-8 w-full text-sm"
            />
          ) : (
            <p className="truncate text-sm font-medium" title={it.name}>
              {it.name || (it.type === "video" ? "Video clip" : "Image")}
            </p>
          )}
          <p className="mt-0.5 text-xs text-[var(--text-3)]">
            {kindLine} · {secs(insertDurationMs({ ...it, media_ms: mediaMs }))}
          </p>
        </div>
        <button onClick={onRemove} aria-label="Remove insert" className="-mr-1 -mt-1 rounded-md p-1.5 text-[var(--text-3)] hover:bg-[var(--hover)] hover:text-red-500">
          <IconTrash className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-3.5 space-y-2.5 border-t border-[var(--border)] pt-3">
        <div className={row}>
          <span className={lbl}>Plays</span>
          <select
            value={posValid ? it.position : "end"}
            onChange={(e) => onPatch({ position: e.target.value as InsertPosition })}
            className="input h-8 min-w-0 text-xs"
          >
            <option value="start">At the start (intro)</option>
            {segments.map((s, i) => (
              <option key={s.step_id} value={`after:${s.step_id}`}>
                After scene {sceneLabel(s, i)}
              </option>
            ))}
            <option value="end">At the end (outro)</option>
          </select>
        </div>

        {it.type !== "video" ? (
          <div className={row}>
            <span className={lbl}>Shows for</span>
            <span className="flex items-center gap-3">
              <input
                type="range"
                min={500}
                max={10000}
                step={250}
                value={it.duration_ms || 2000}
                onChange={(e) => onPatch({ duration_ms: Number(e.target.value) })}
                className="min-w-0 flex-1 accent-[#1E8F8E]"
              />
              <span className="w-12 text-right font-mono text-xs">{((it.duration_ms || 2000) / 1000).toFixed(1)} s</span>
            </span>
          </div>
        ) : (
          <>
            <div className={row}>
              <span className={lbl}>Use clip from</span>
              <span className="flex items-center gap-2 text-xs">
                <SecInput value={it.trim_start_ms ?? 0} max={mediaMs} onChange={(ms) => onPatch({ trim_start_ms: ms })} />
                <span className="text-[var(--text-3)]">to</span>
                <SecInput
                  value={it.trim_end_ms ?? mediaMs ?? 0}
                  max={mediaMs}
                  onChange={(ms) => onPatch({ trim_end_ms: ms >= (mediaMs ?? Infinity) ? undefined : ms })}
                />
                <span className="text-[var(--text-3)]">seconds, of {secs(mediaMs)}</span>
              </span>
            </div>
            <div className={row}>
              <span className={lbl}>Sound</span>
              <label className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={it.keep_audio !== false}
                  disabled={asset ? !asset.has_audio : false}
                  onChange={(e) => onPatch({ keep_audio: e.target.checked })}
                  className="accent-[#1E8F8E]"
                />
                {asset && !asset.has_audio ? "This clip has no sound" : "Play the clip's own audio"}
              </label>
            </div>
          </>
        )}

        {it.type === "image" && (
          <div className={row}>
            <span className={lbl}>Image fit</span>
            <select
              value={it.fit ?? "contain"}
              onChange={(e) => onPatch({ fit: e.target.value as "cover" | "contain" })}
              className="input h-8 min-w-0 text-xs"
            >
              <option value="contain">Whole image on a dark card</option>
              <option value="cover">Fill the frame (crop edges)</option>
            </select>
          </div>
        )}
      </div>
    </li>
  );
}

function SecInput({ value, max, onChange }: { value: number; max?: number; onChange: (ms: number) => void }) {
  // While focused the field shows what the user typed, not the stored value
  // re-formatted on every keystroke — that snapped a cleared field straight
  // back to "0.0", so replacing "1.0" meant caret-surgery around the point.
  // Only a parseable number is pushed up; the draft is dropped on blur.
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? (value / 1000).toFixed(1);
  return (
    <input
      type="number"
      min={0}
      max={max ? max / 1000 : undefined}
      step={0.1}
      value={shown}
      onFocus={(e) => {
        setDraft((value / 1000).toFixed(1));
        e.currentTarget.select();
      }}
      onChange={(e) => {
        const raw = e.target.value;
        setDraft(raw);
        const n = Number(raw);
        if (raw.trim() === "" || !Number.isFinite(n)) return;
        const ms = Math.max(0, Math.round(n * 1000));
        onChange(max ? Math.min(ms, max) : ms);
      }}
      onBlur={() => setDraft(null)}
      className="input h-7 w-16 px-1.5 text-xs"
    />
  );
}

/* ------------------------------------------------------------------ */

const CORNERS: { id: string; label: string; x: (w: number) => number; y: (h: number) => number }[] = [
  { id: "tl", label: "↖", x: () => 0.03, y: () => 0.04 },
  { id: "tr", label: "↗", x: (w) => 1 - w - 0.03, y: () => 0.04 },
  { id: "c", label: "•", x: (w) => (1 - w) / 2, y: (h) => (1 - h) / 2 },
  { id: "bl", label: "↙", x: () => 0.03, y: (h) => 1 - h - 0.04 },
  { id: "br", label: "↘", x: (w) => 1 - w - 0.03, y: (h) => 1 - h - 0.04 },
];

function OverlayRow({
  ov,
  asset,
  selected,
  onSelect,
  curMs,
  totalMs,
  onPatch,
  onCutout,
  onRemove,
}: {
  ov: MediaOverlay;
  asset?: LibraryAsset;
  selected: boolean;
  onSelect: () => void;
  curMs: number;
  totalMs: number;
  onPatch: (p: Partial<MediaOverlay>) => void;
  onCutout: () => void;
  onRemove: () => void;
}) {
  const mode = typeof ov.range === "object" ? "custom" : ov.range;
  const custom = typeof ov.range === "object" ? ov.range : null;
  const canCut = ov.type === "image" && !!asset;
  const setNobg = (on: boolean) => {
    if (!asset) return;
    const key = assetKey(asset, on);
    if (key) onPatch({ nobg: on && !!asset.nobg_key, media_key: key });
  };
  // the cut-out finished after the overlay was placed: switch to it
  useEffect(() => {
    if (ov.nobg && asset?.nobg_key && ov.media_key !== asset.nobg_key) onPatch({ media_key: asset.nobg_key });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asset?.nobg_key]);
  return (
    <li
      onClick={onSelect}
      className={`cursor-pointer rounded-xl border p-2.5 ${selected ? "border-[#1E8F8E] ring-1 ring-[#1E8F8E]/40" : "border-[var(--border)]"}`}
    >
      <div className="flex items-center gap-2">
        <span className="h-8 w-8 flex-none overflow-hidden rounded-md" style={{ backgroundImage: CHECKER, backgroundSize: "8px 8px" }}>
          {ov.type === "image" ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={mediaUrl(ov.media_key)} alt="" className="h-full w-full object-contain" />
          ) : asset?.poster_key ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={mediaUrl(asset.poster_key)} alt="" className="h-full w-full object-cover" />
          ) : null}
        </span>
        <span className="min-w-0 flex-1 truncate text-xs font-medium">{ov.name || (ov.type === "video" ? "Clip" : "Logo")}</span>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          aria-label="Remove overlay"
          className="rounded-md p-1 text-[var(--text-3)] hover:bg-[var(--hover)] hover:text-red-500"
        >
          <IconTrash className="h-3.5 w-3.5" />
        </button>
      </div>
      {selected && (
        <div className="mt-2 grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-1.5 text-[11px] text-[var(--text-2)]" onClick={(e) => e.stopPropagation()}>
          <span>Shows</span>
          <select
            value={mode}
            onChange={(e) => {
              const v = e.target.value;
              onPatch({
                range:
                  v === "custom"
                    ? { start_ms: Math.round(curMs), end_ms: Math.round(Math.min(totalMs, curMs + 5000)) }
                    : (v as "all" | "body"),
              });
            }}
            className="input h-7 text-xs"
          >
            <option value="all">Whole video (incl. inserted clips)</option>
            <option value="body">During the recording only</option>
            <option value="custom">Custom time range</option>
          </select>
          {custom && (
            <>
              <span>From</span>
              <span className="flex items-center gap-1">
                <SecInput value={custom.start_ms} max={totalMs} onChange={(ms) => onPatch({ range: { ...custom, start_ms: ms } })} />
                <button onClick={() => onPatch({ range: { ...custom, start_ms: Math.round(curMs) } })} className="text-[#1E8F8E] hover:underline">
                  playhead
                </button>
                <span>to</span>
                <SecInput value={custom.end_ms} max={totalMs} onChange={(ms) => onPatch({ range: { ...custom, end_ms: ms } })} />
                <button onClick={() => onPatch({ range: { ...custom, end_ms: Math.round(curMs) } })} className="text-[#1E8F8E] hover:underline">
                  playhead
                </button>
              </span>
            </>
          )}
          <span>Place</span>
          <span className="flex gap-1">
            {CORNERS.map((c) => (
              <button
                key={c.id}
                onClick={() => onPatch({ x: c.x(ov.w), y: c.y(ov.h) })}
                className="h-6 w-6 rounded-md border border-[var(--border)] text-xs hover:bg-[var(--hover)]"
                title="Snap to this position"
              >
                {c.label}
              </button>
            ))}
            <span className="ml-1 self-center text-[var(--text-3)]">or drag on the preview</span>
          </span>
          <span>Opacity</span>
          <span className="flex items-center gap-2">
            <input
              type="range"
              min={0.1}
              max={1}
              step={0.05}
              value={ov.opacity ?? 1}
              onChange={(e) => onPatch({ opacity: Number(e.target.value) })}
              className="flex-1 accent-[#1E8F8E]"
            />
            <span className="w-9 text-right font-mono">{Math.round((ov.opacity ?? 1) * 100)}%</span>
          </span>
          {canCut && (
            <>
              <span>Background</span>
              {asset!.bg_status === "ready" ? (
                <label className="flex items-center gap-1.5">
                  Removed
                  <input type="checkbox" checked={!!ov.nobg} onChange={(e) => setNobg(e.target.checked)} className="accent-[#1E8F8E]" />
                </label>
              ) : asset!.bg_status === "running" ? (
                <span className="flex items-center gap-1.5">
                  <Spinner /> Removing…
                </span>
              ) : (
                <button
                  onClick={() => {
                    onCutout();
                    onPatch({ nobg: true });
                  }}
                  className="justify-self-start text-[#1E8F8E] hover:underline"
                >
                  Remove background
                </button>
              )}
            </>
          )}
          {ov.type === "video" && (
            <>
              <span />
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={ov.loop !== false} onChange={(e) => onPatch({ loop: e.target.checked })} className="accent-[#1E8F8E]" />
                Loop the clip while it shows
              </label>
            </>
          )}
        </div>
      )}
    </li>
  );
}

/* ------------------------------------------------------------------ */

function MusicSection({
  music,
  asset,
  patchSpec,
}: {
  music: MusicSettings;
  asset?: LibraryAsset;
  patchSpec: (p: Partial<EditSpec>) => void;
}) {
  const set = (p: Partial<MusicSettings>) => patchSpec({ music: { ...music, ...p } });
  return (
    <section className="border-t border-[var(--border)] pt-4">
      <label className="flex cursor-pointer items-center justify-between">
        <span>
          <span className="text-sm font-medium">Background music</span>
          <span className="mt-0.5 block text-xs text-[var(--text-3)]">
            {music.storage_key
              ? `${music.name || asset?.name || "Your track"} — loops under the narration.`
              : music.enabled
                ? "No track chosen yet — pick “Use as music” on an audio file above, or nothing will play."
                : "Pick “Use as music” on an audio file above."}
          </span>
        </span>
        <input
          type="checkbox"
          checked={music.enabled}
          onChange={(e) => set({ enabled: e.target.checked })}
          className="h-4 w-8 accent-[#1E8F8E]"
        />
      </label>
      {/* volume / ducking / fades only mean something once a track is chosen */}
      {music.enabled && music.storage_key && (
        <div className="mt-3 grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-2 text-xs text-[var(--text-2)]">
          <span>Volume</span>
          <span className="flex items-center gap-2">
            <input
              type="range"
              min={-30}
              max={-4}
              step={1}
              value={music.gain_db ?? -18}
              onChange={(e) => {
                set({ gain_db: Number(e.target.value) });
                // let the preview play the track for a moment so the level is audible
                window.dispatchEvent(new Event(MUSIC_AUDITION_EVENT));
              }}
              className="flex-1 accent-[#1E8F8E]"
            />
            <span className="w-12 text-right font-mono">{music.gain_db ?? -18} dB</span>
          </span>
          <span />
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={music.duck !== false} onChange={(e) => set({ duck: e.target.checked })} className="accent-[#1E8F8E]" />
            Lower the music while someone speaks
          </label>
          <span>Fade in</span>
          <span className="flex items-center gap-2">
            <input type="range" min={0} max={5000} step={250} value={music.fade_in_ms ?? 1000}
              onChange={(e) => set({ fade_in_ms: Number(e.target.value) })} className="flex-1 accent-[#1E8F8E]" />
            <span className="w-12 text-right font-mono">{((music.fade_in_ms ?? 1000) / 1000).toFixed(1)}s</span>
          </span>
          <span>Fade out</span>
          <span className="flex items-center gap-2">
            <input type="range" min={0} max={8000} step={250} value={music.fade_out_ms ?? 2000}
              onChange={(e) => set({ fade_out_ms: Number(e.target.value) })} className="flex-1 accent-[#1E8F8E]" />
            <span className="w-12 text-right font-mono">{((music.fade_out_ms ?? 2000) / 1000).toFixed(1)}s</span>
          </span>
          {music.storage_key && (
            <>
              <span>Start at</span>
              <span className="flex items-center gap-2">
                <SecInput value={music.start_ms ?? 0} max={asset?.duration_ms ?? undefined} onChange={(ms) => set({ start_ms: ms })} />
                <span className="text-[var(--text-3)]">into the track</span>
                <button
                  onClick={() => set({ storage_key: null, asset_id: null, name: null, start_ms: 0 })}
                  className="ml-auto text-[#1E8F8E] hover:underline"
                >
                  Remove track
                </button>
              </span>
            </>
          )}
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------------------------------ */

function RecordingPicker({ onClose, onPick }: { onClose: () => void; onPick: (r: ReusableRecording) => Promise<void> }) {
  const [recs, setRecs] = useState<ReusableRecording[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    listReusableRecordings().then(setRecs).catch((e) => setErr((e as Error).message));
  }, []);
  return (
    <ModalShell
      title="Reuse a recording"
      onClose={onClose}
      maxWidth="max-w-2xl"
      footer={<p className="text-xs text-[var(--text-3)]">The recording is copied into your library, so it keeps working even if its project is deleted.</p>}
    >
      {err && <p className="text-sm text-red-500">{err}</p>}
      {recs === null && !err ? (
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      ) : recs && recs.length === 0 ? (
        <p className="py-8 text-center text-sm text-[var(--text-3)]">No recordings yet.</p>
      ) : (
        <div className="grid grid-cols-2 gap-3 pb-2 sm:grid-cols-3">
          {(recs ?? []).map((r) => (
            <button
              key={r.session_id}
              disabled={!!busy}
              onClick={async () => {
                setBusy(r.session_id);
                try {
                  await onPick(r);
                } catch (e) {
                  setErr((e as Error).message);
                  setBusy(null);
                }
              }}
              className="overflow-hidden rounded-xl border border-[var(--border)] text-left hover:border-[#1E8F8E] disabled:opacity-60"
            >
              <span className="relative block aspect-video bg-[var(--bg)]">
                {r.poster && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={mediaUrl(r.poster)} alt="" className="h-full w-full object-cover" />
                )}
                {busy === r.session_id && (
                  <span className="absolute inset-0 flex items-center justify-center bg-black/40">
                    <Spinner />
                  </span>
                )}
                {r.duration_ms ? (
                  <span className="absolute bottom-1 right-1 rounded bg-black/70 px-1 font-mono text-[10px] text-white">{secs(r.duration_ms)}</span>
                ) : null}
              </span>
              <span className="block truncate px-2 py-1.5 text-xs font-medium">{r.project_name}</span>
            </button>
          ))}
        </div>
      )}
    </ModalShell>
  );
}

function BgCompare({ a, onClose }: { a: LibraryAsset; onClose: () => void }) {
  return (
    <ModalShell
      title="Background removal"
      onClose={onClose}
      maxWidth="max-w-3xl"
      footer={
        <p className="text-xs text-[var(--text-3)]">
          The original is kept. Choose per overlay: open it under “On top of the video” and toggle <b>Background → Removed</b>.
        </p>
      }
    >
      <div className="grid grid-cols-2 gap-4 pb-2">
        {[
          { label: "Original", key: a.normalized_key },
          { label: "Background removed", key: a.nobg_key },
        ].map((x) => (
          <figure key={x.label}>
            <div className="flex aspect-square items-center justify-center rounded-xl" style={{ backgroundImage: CHECKER, backgroundSize: "16px 16px" }}>
              {x.key && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={mediaUrl(x.key)} alt={x.label} className="max-h-full max-w-full object-contain" />
              )}
            </div>
            <figcaption className="mt-1 text-center text-xs text-[var(--text-2)]">{x.label}</figcaption>
          </figure>
        ))}
      </div>
    </ModalShell>
  );
}
