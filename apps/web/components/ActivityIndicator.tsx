"use client";

/**
 * Header indicator for work in flight across all of the user's projects:
 * recordings being processed, documents being written, videos rendering.
 *
 * Polls /activity every 4s while something is running and every 20s when idle
 * (a new upload shows up within one idle tick). Hidden when there is nothing to
 * show, so it costs no header space in the common case.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ACTIVITY_EVENT, getActivity, type ActivityItem } from "@/lib/api";
import { ProgressBar } from "@/components/ProgressBar";
import { IconCheck, IconDoc, IconVideo, IconX } from "@/components/icons";
import { Spinner } from "@/components/ui";

const KIND_LABEL: Record<ActivityItem["kind"], string> = {
  processing: "Processing recording",
  document: "Writing document",
  render: "Rendering video",
};

const ACTIVE = new Set(["running", "queued", "stalled"]);

export function ActivityIndicator() {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  const active = items.filter((i) => ACTIVE.has(i.status));

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      const next = await getActivity().catch(() => [] as ActivityItem[]);
      if (!alive) return;
      setItems(next);
      const busy = next.some((i) => ACTIVE.has(i.status));
      timer = setTimeout(tick, busy ? 4000 : 20000);
    };
    const poke = () => {
      clearTimeout(timer);
      void tick();
    };
    void tick();
    window.addEventListener(ACTIVITY_EVENT, poke);
    return () => {
      alive = false;
      clearTimeout(timer);
      window.removeEventListener(ACTIVITY_EVENT, poke);
    };
    // re-poll immediately after navigating (e.g. right after starting an upload)
  }, [pathname]);

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

  if (items.length === 0) return null;

  const lead = active[0];
  return (
    <div ref={root} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={`flex h-9 items-center gap-2 rounded-lg border px-3 text-[13px] font-medium transition-colors ${
          active.length
            ? "border-[var(--brand)]/40 bg-[var(--brand-soft)] text-[var(--brand)]"
            : "border-[var(--border)] text-[var(--text-2)] hover:bg-[var(--hover)]"
        }`}
      >
        {active.length ? <Spinner className="h-3.5 w-3.5" /> : <IconCheck width={14} height={14} />}
        <span className="hidden sm:inline">
          {active.length
            ? active.length === 1 && lead?.progress != null
              ? `${KIND_LABEL[lead.kind]} · ${Math.round(lead.progress * 100)}%`
              : `${active.length} in progress`
            : "All done"}
        </span>
        <span className="sm:hidden">{active.length || ""}</span>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-2 w-[340px] max-w-[calc(100vw-32px)] overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-2xl shadow-black/20"
        >
          <div className="border-b border-[var(--border)] px-4 py-2.5">
            <span className="eyebrow">Activity</span>
          </div>
          <ul className="max-h-[60vh] divide-y divide-[var(--border)] overflow-y-auto">
            {items.map((i) => (
              <li key={`${i.kind}-${i.href}`}>
                <Link href={i.href} role="menuitem" onClick={() => setOpen(false)} className="block px-4 py-3 hover:bg-[var(--hover)]">
                  <div className="flex items-center gap-2">
                    <span className="flex-none text-[var(--brand)]">
                      {i.kind === "document" ? <IconDoc width={15} height={15} /> : <IconVideo width={15} height={15} />}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-[var(--text)]">{i.project_name}</span>
                    {i.status === "error" ? (
                      <IconX width={14} height={14} className="text-[var(--error)]" />
                    ) : !ACTIVE.has(i.status) ? (
                      <IconCheck width={14} height={14} className="text-[var(--brand)]" />
                    ) : i.progress != null ? (
                      <span className="font-mono text-[12px] text-[var(--text-2)]">{Math.round(i.progress * 100)}%</span>
                    ) : null}
                  </div>
                  <p className="mt-0.5 truncate pl-[23px] text-[12px] text-[var(--text-3)]">
                    {i.status === "stalled"
                      ? "Waiting — the server is busy"
                      : i.message || KIND_LABEL[i.kind]}
                  </p>
                  {ACTIVE.has(i.status) && (
                    <div className="pl-[23px]">
                      <ProgressBar value={i.status === "queued" ? null : i.progress} className="mt-1.5" tone={i.status === "stalled" ? "warn" : "brand"} />
                    </div>
                  )}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
