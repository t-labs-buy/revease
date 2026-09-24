"use client";

/**
 * Download a capture's video: the original recording/upload, or the processed
 * full-quality MP4. The original is kept for a limited time after processing
 * (retention), so the menu says when it fell back to the processed file.
 */

import { useEffect, useRef, useState } from "react";
import { downloadSessionVideo } from "@/lib/api";
import { IconChevronDown, IconDownload } from "@/components/icons";
import { Spinner } from "@/components/ui";
import { fmtBytes } from "@/lib/upload";

export function DownloadVideoButton({ sessionId, compact = false }: { sessionId: string; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<"original" | "processed" | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const go = async (variant: "original" | "processed") => {
    setBusy(variant);
    setNote(null);
    try {
      const d = await downloadSessionVideo(sessionId, variant);
      const size = d.size ? ` (${fmtBytes(d.size)})` : "";
      setNote(
        d.fallback
          ? `The original is no longer stored — downloading the processed MP4${size}.`
          : `Downloading ${d.filename}${size}`,
      );
      setOpen(false);
    } catch (e) {
      setNote(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(null);
    }
  };

  // Inside a card that is itself a link: keep clicks from navigating.
  const stop = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  return (
    <div ref={root} className="relative inline-block" onClick={stop}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title="Download video"
        className={compact ? "btn btn-ghost btn-sm h-8 w-8 p-0 text-[var(--text-2)]" : "btn btn-secondary btn-sm gap-1.5"}
      >
        {busy ? <Spinner className="h-3.5 w-3.5" /> : <IconDownload width={14} height={14} />}
        {!compact && (
          <>
            Download <IconChevronDown width={13} height={13} />
          </>
        )}
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-40 mt-2 w-60 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] p-1.5 text-left shadow-2xl shadow-black/20"
        >
          <button role="menuitem" disabled={busy !== null} onClick={() => void go("original")}
            className="block w-full rounded-lg px-3 py-2 text-left hover:bg-[var(--hover)] disabled:opacity-60">
            <span className="block text-[13px] font-medium text-[var(--text)]">Original recording</span>
            <span className="block text-[11.5px] text-[var(--text-3)]">Exactly as recorded or uploaded</span>
          </button>
          <button role="menuitem" disabled={busy !== null} onClick={() => void go("processed")}
            className="block w-full rounded-lg px-3 py-2 text-left hover:bg-[var(--hover)] disabled:opacity-60">
            <span className="block text-[13px] font-medium text-[var(--text)]">Processed MP4</span>
            <span className="block text-[11.5px] text-[var(--text-3)]">Full quality, plays everywhere</span>
          </button>
        </div>
      )}
      {note && !compact && <p className="mt-1.5 max-w-xs text-[12px] text-[var(--text-3)]">{note}</p>}
    </div>
  );
}
