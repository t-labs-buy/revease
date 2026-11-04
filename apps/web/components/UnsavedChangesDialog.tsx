"use client";

/** Asked when leaving an editor with unsaved edits: save, discard, or stay. */
export function UnsavedChangesDialog({
  busy = false,
  onSave,
  onDiscard,
  onStay,
}: {
  busy?: boolean;
  onSave: () => void;
  onDiscard: () => void;
  onStay: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4 backdrop-blur-[2px]"
      onClick={busy ? undefined : onStay}
      role="dialog"
      aria-modal="true"
      aria-labelledby="unsaved-title"
    >
      <div
        className="w-full max-w-md rounded-2xl bg-[var(--card)] p-5 shadow-2xl ring-1 ring-[var(--border)]"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="unsaved-title" className="text-[15px] font-semibold text-[var(--text)]">
          You have unsaved changes
        </h3>
        <p className="mt-1 text-sm leading-relaxed text-[var(--text-2)]">
          If you leave now, your edits to this video will be lost.
        </p>
        <div className="mt-5 grid grid-cols-1 gap-2 sm:grid-cols-3">
          <button
            onClick={onStay}
            disabled={busy}
            className="btn btn-secondary btn-sm whitespace-nowrap"
          >
            Stay
          </button>
          <button
            onClick={onDiscard}
            disabled={busy}
            className="btn btn-secondary btn-sm whitespace-nowrap"
          >
            Leave without saving
          </button>
          <button
            onClick={onSave}
            disabled={busy}
            className="btn btn-secondary btn-sm whitespace-nowrap"
          >
            {busy ? "Saving…" : "Save and leave"}
          </button>
        </div>
      </div>
    </div>
  );
}
