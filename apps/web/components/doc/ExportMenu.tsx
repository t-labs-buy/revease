"use client";

import { useEffect, useRef, useState } from "react";
import type { DocExportFormat } from "@/lib/api";
import { IconChevronDown, IconDownload } from "@/components/icons";
import { Spinner } from "@/components/ui";

const FORMATS: { key: DocExportFormat; label: string; hint: string }[] = [
  { key: "docx", label: "Word (.docx)", hint: "Editable in Word or Pages" },
  { key: "pdf", label: "PDF (.pdf)", hint: "Print-ready" },
  { key: "md", label: "Markdown (.md)", hint: "For wikis and repos" },
];

export function ExportMenu({
  onExport,
  disabled,
}: {
  onExport: (format: DocExportFormat) => Promise<void>;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<DocExportFormat | null>(null);
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

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        className="btn btn-secondary btn-sm gap-1.5"
      >
        <IconDownload width={14} height={14} /> Export <IconChevronDown width={13} height={13} />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-40 mt-2 w-56 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] p-1.5 shadow-2xl shadow-black/20"
        >
          {FORMATS.map((f) => (
            <button
              key={f.key}
              role="menuitem"
              disabled={busy !== null}
              onClick={async () => {
                setBusy(f.key);
                try {
                  await onExport(f.key);
                  setOpen(false);
                } finally {
                  setBusy(null);
                }
              }}
              className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left transition-colors hover:bg-[var(--hover)] disabled:opacity-60"
            >
              <span>
                <span className="block text-[13px] font-medium text-[var(--text)]">{f.label}</span>
                <span className="block text-[11.5px] text-[var(--text-3)]">{f.hint}</span>
              </span>
              {busy === f.key && <Spinner className="text-[var(--brand)]" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
