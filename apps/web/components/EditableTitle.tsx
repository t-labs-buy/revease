"use client";

/**
 * A heading you can click to rename. Enter or clicking away saves, Escape
 * cancels. An unchanged or blank name is not sent: the server would reject a
 * blank one, and an unchanged one would lock the auto-title for no reason.
 */

import { useEffect, useRef, useState } from "react";
import { IconPencil } from "@/components/icons";

export function EditableTitle({
  value,
  onSave,
  className = "",
  maxLength = 200,
}: {
  value: string;
  onSave: (name: string) => Promise<void>;
  className?: string;
  maxLength?: number;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!editing) setDraft(value);
  }, [value, editing]);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  async function commit() {
    const name = draft.trim().replace(/\s+/g, " ");
    if (!name || name === value) {
      setEditing(false);
      setDraft(value);
      setError(null);
      return;
    }
    setBusy(true);
    try {
      await onSave(name);
      setEditing(false);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <div>
        <input
          ref={inputRef}
          value={draft}
          maxLength={maxLength}
          disabled={busy}
          aria-label="Project name"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => void commit()}
          onKeyDown={(e) => {
            if (e.key === "Enter") void commit();
            if (e.key === "Escape") {
              setDraft(value);
              setEditing(false);
              setError(null);
            }
          }}
          className={`${className} w-full min-w-0 rounded-lg bg-[var(--hover)] px-2 -mx-2 outline-none ring-2 ring-[var(--brand)]`}
        />
        {error && <p className="mt-1 text-sm text-red-500">{error}</p>}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      title="Rename"
      // -mx-2 + px-2 keeps the text aligned with the line below while the hover
      // background bleeds out. The cap must add those 1rem back: a plain
      // max-w-full squeezed the text 16px narrower than itself and wrapped or
      // clipped even a short name ("AB|C").
      className="group -mx-2 inline-flex max-w-[calc(100%+1rem)] items-center gap-2 rounded-lg px-2 text-left hover:bg-[var(--hover)]"
    >
      <span className={`${className} min-w-0 break-words`}>{value}</span>
      <IconPencil
        width={18}
        height={18}
        aria-hidden
        className="flex-none text-[var(--text-3)] opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
      />
      <span className="sr-only">Rename project</span>
    </button>
  );
}
