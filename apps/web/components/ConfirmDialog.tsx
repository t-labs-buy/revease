"use client";

/** Styled in-app confirmation (replaces window.confirm) — danger-action variant. */
export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Delete",
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string;
  message: string;
  confirmLabel?: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4 backdrop-blur-[2px]"
      onClick={busy ? undefined : onCancel}
    >
      <div
        className="w-full max-w-sm rounded-2xl bg-[var(--card)] p-5 shadow-2xl ring-1 ring-[var(--border)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 flex-none items-center justify-center rounded-full bg-red-500/10 text-lg">
            🗑
          </span>
          <div className="min-w-0">
            <h3 className="text-[15px] font-semibold text-[var(--text)]">{title}</h3>
            <p className="mt-1 text-sm leading-relaxed text-[var(--text-2)]">{message}</p>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onCancel} disabled={busy} className="btn btn-secondary btn-sm">
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={busy}
            className="btn btn-sm bg-red-500 text-white hover:bg-red-600 disabled:opacity-50"
          >
            {busy ? "Deleting…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
