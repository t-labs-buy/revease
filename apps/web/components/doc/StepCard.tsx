"use client";

import { useState } from "react";
import { mediaUrl, type DocStepV2 } from "@/lib/api";
import { AutosizeTextarea } from "@/components/doc/AutosizeTextarea";
import { mmss, TipCallout } from "@/components/doc/DocView";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import {
  IconArrowDown,
  IconArrowUp,
  IconCamera,
  IconLightbulb,
  IconPlus,
  IconTrash,
  IconX,
} from "@/components/icons";
import { Spinner } from "@/components/ui";

export function StepCard({
  step,
  index,
  total,
  busy,
  canPickFrames,
  autoFocus,
  onPatch,
  onMoveUp,
  onMoveDown,
  onDelete,
  onChangeFrame,
  onRemoveSnapshot,
}: {
  step: DocStepV2;
  index: number;
  total: number;
  busy: boolean;
  canPickFrames: boolean;
  autoFocus?: boolean;
  onPatch: (patch: Partial<DocStepV2>) => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onDelete: () => void;
  onChangeFrame: () => void;
  onRemoveSnapshot: () => void;
}) {
  const [confirm, setConfirm] = useState(false);
  const snap = step.snapshot;
  const iconBtn = "btn btn-ghost btn-sm h-8 w-8 p-0 text-[var(--text-3)] hover:text-[var(--text)]";

  return (
    <li className="card group p-4 sm:p-5" aria-label={`Step ${index + 1}`}>
      {confirm && (
        <ConfirmDialog
          title="Delete this step?"
          message={`"${step.title || `Step ${index + 1}`}" and its snapshot will be removed from the document.`}
          confirmLabel="Delete step"
          onConfirm={() => {
            setConfirm(false);
            onDelete();
          }}
          onCancel={() => setConfirm(false)}
        />
      )}

      {/* title row */}
      <div className="flex flex-wrap items-start gap-2">
        <span className="mt-1 flex h-6 w-6 flex-none items-center justify-center rounded-full bg-[var(--brand)] text-xs font-semibold text-white">
          {index + 1}
        </span>
        <input
          value={step.title}
          autoFocus={autoFocus}
          onChange={(e) => onPatch({ title: e.target.value })}
          placeholder="Step title"
          aria-label={`Step ${index + 1} title`}
          className="min-w-[200px] flex-1 rounded-md bg-transparent px-1.5 py-0.5 text-[16px] font-semibold text-[var(--text)] outline-none ring-[#1E8F8E]/30 placeholder:font-normal placeholder:text-[var(--text-3)] focus:bg-[var(--hover)] focus:ring-2"
        />
        <div className="ml-auto flex items-center gap-0.5">
          <button type="button" onClick={onMoveUp} disabled={index === 0} aria-label="Move step up" title="Move up" className={iconBtn}>
            <IconArrowUp width={15} height={15} />
          </button>
          <button
            type="button"
            onClick={onMoveDown}
            disabled={index === total - 1}
            aria-label="Move step down"
            title="Move down"
            className={iconBtn}
          >
            <IconArrowDown width={15} height={15} />
          </button>
          <button
            type="button"
            onClick={() => setConfirm(true)}
            aria-label="Delete step"
            title="Delete"
            className={`${iconBtn} hover:text-[var(--error)]`}
          >
            <IconTrash width={15} height={15} />
          </button>
        </div>
      </div>

      {/* body */}
      <AutosizeTextarea
        value={step.body}
        minRows={2}
        onChange={(e) => onPatch({ body: e.target.value })}
        placeholder="What the reader should do, and what they will see. Use **bold** for UI labels."
        aria-label={`Step ${index + 1} instructions`}
        className="mt-3 text-[14.5px] leading-relaxed"
      />

      {/* tip */}
      {step.tip == null ? (
        <button
          type="button"
          onClick={() => onPatch({ tip: "" })}
          className="btn btn-ghost btn-sm mt-2 -ml-1 gap-1.5 text-[var(--text-3)]"
        >
          <IconLightbulb width={14} height={14} /> Add tip
        </button>
      ) : (
        <TipCallout>
          <div className="flex items-start gap-2">
            <AutosizeTextarea
              value={step.tip}
              minRows={1}
              onChange={(e) => onPatch({ tip: e.target.value })}
              placeholder="A shortcut, a caveat, or what to do if the screen looks different"
              aria-label={`Step ${index + 1} tip`}
              className="border-0 bg-transparent p-0 text-[13.5px] focus:ring-0"
            />
            <button
              type="button"
              onClick={() => onPatch({ tip: null })}
              aria-label="Remove tip"
              title="Remove tip"
              className="flex-none text-[var(--text-3)] hover:text-[var(--text)]"
            >
              <IconX width={14} height={14} />
            </button>
          </div>
        </TipCallout>
      )}

      {/* snapshot */}
      {snap?.key ? (
        <figure className="relative mt-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`${mediaUrl(snap.key)}?v=${snap.t ?? 0}`}
            alt={`Step ${index + 1} screenshot`}
            className={`w-full rounded-lg border border-[var(--border)] bg-[var(--navy)] ${busy ? "opacity-60" : ""}`}
          />
          {busy && (
            <span className="absolute inset-0 flex items-center justify-center gap-2 rounded-lg bg-black/40 text-sm font-medium text-white">
              <Spinner /> Capturing frame…
            </span>
          )}
          <figcaption className="mt-1.5 flex flex-wrap items-center gap-2 text-[12px] text-[var(--text-3)]">
            <span>Frame at {mmss(snap.t)}</span>
            {snap.bbox_norm && <span>· click highlighted</span>}
            <span className="ml-auto flex items-center gap-1.5 sm:opacity-0 sm:transition-opacity sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
              {canPickFrames && (
                <button type="button" onClick={onChangeFrame} disabled={busy} className="btn btn-secondary btn-sm gap-1.5">
                  <IconCamera width={13} height={13} /> Change frame
                </button>
              )}
              <button type="button" onClick={onRemoveSnapshot} disabled={busy} className="btn btn-ghost btn-sm gap-1">
                <IconX width={13} height={13} /> Remove
              </button>
            </span>
          </figcaption>
        </figure>
      ) : busy ? (
        <div className="mt-3 flex items-center justify-center gap-2 rounded-lg border border-dashed border-[var(--border-strong)] py-8 text-sm text-[var(--text-2)]">
          <Spinner /> Capturing frame…
        </div>
      ) : canPickFrames ? (
        <button
          type="button"
          onClick={onChangeFrame}
          className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-[var(--border-strong)] py-6 text-sm text-[var(--text-2)] transition-colors hover:border-[var(--brand)] hover:text-[var(--brand)]"
        >
          <IconPlus width={15} height={15} /> Add a snapshot from the recording
        </button>
      ) : null}
    </li>
  );
}
