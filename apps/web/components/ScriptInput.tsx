"use client";

import { useRef, useState } from "react";

// Mirrors SCRIPT_MAX_CHARS in apps/api/app/schemas.py.
export const SCRIPT_MAX_CHARS = 50_000;

/** A narration script for a recording without a voiceover: type or paste it, or
 * load a .txt / .md / .srt file. The file is read in the browser (same as the
 * Skills import) — the API only ever receives text. */
export function ScriptInput({
  value,
  onChange,
  rows = 6,
  disabled = false,
}: {
  value: string;
  onChange: (text: string) => void;
  rows?: number;
  disabled?: boolean;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadFile(file: File) {
    setError(null);
    try {
      const text = await file.text();
      if (text.length > SCRIPT_MAX_CHARS) {
        setError(`That file is too long (limit ${SCRIPT_MAX_CHARS.toLocaleString()} characters).`);
        return;
      }
      onChange(text);
    } catch {
      setError("Could not read that file.");
    }
  }

  return (
    <div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        maxLength={SCRIPT_MAX_CHARS}
        disabled={disabled}
        placeholder="Paste the narration here. Each sentence becomes a scene, matched to the video automatically."
        className="input w-full resize-y text-left text-sm leading-relaxed"
      />
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--text-3)]">
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          disabled={disabled}
          className="font-medium text-[#1E8F8E] hover:underline disabled:opacity-50"
        >
          Load a .txt, .md or .srt file
        </button>
        <span>
          Optional: start a line with <code>[0:42]</code> to pin it to that moment, and use{" "}
          <code>[pause:1.5]</code> for a pause.
        </span>
      </div>
      <input
        ref={fileRef}
        type="file"
        accept=".txt,.md,.markdown,.srt,text/plain,text/markdown"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void loadFile(f);
          e.target.value = "";
        }}
      />
      {error && <p className="mt-1.5 text-xs text-red-400">{error}</p>}
    </div>
  );
}
