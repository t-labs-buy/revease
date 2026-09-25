"use client";

import { useState } from "react";
import { createShare, setShareDownload, shareLink } from "@/lib/api";
import { IconShare } from "@/components/icons";

export function ShareButton({
  projectId,
  kind = "video",
  className = "btn btn-secondary btn-sm",
}: {
  projectId: string;
  kind?: "video" | "doc";
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [link, setLink] = useState("");
  const [token, setToken] = useState("");
  const [allowDownload, setAllowDownload] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function share() {
    setBusy(true);
    setError(null);
    try {
      const s = await createShare(projectId, kind);
      setToken(s.token);
      setLink(shareLink(s.token));
      setAllowDownload(s.allow_download);
      setOpen(true);
    } catch (e) {
      setError(String(e));
      setOpen(true);
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    await navigator.clipboard.writeText(link);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  async function toggleDownload(next: boolean) {
    setAllowDownload(next); // optimistic
    setSaving(true);
    try {
      const s = await setShareDownload(token, next);
      setAllowDownload(s.allow_download);
    } catch (e) {
      setAllowDownload(!next);
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="relative">
      <button onClick={share} disabled={busy} className={className}>
        <IconShare width={15} height={15} /> {busy ? "…" : "Share"}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-80 rounded-xl border border-[var(--border)] bg-[var(--card)] p-3 shadow-2xl">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium">Public link</span>
            <button onClick={() => setOpen(false)} className="btn btn-ghost btn-sm">
              ✕
            </button>
          </div>
          {error ? (
            <p className="text-sm text-red-600">{error}</p>
          ) : (
            <>
              <div className="flex gap-2">
                <input readOnly value={link} className="input flex-1 text-xs" />
                <button onClick={copy} className="btn btn-primary btn-sm">
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              {kind === "video" && (
                <label className="mt-3 flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={allowDownload}
                    disabled={saving}
                    onChange={(e) => void toggleDownload(e.target.checked)}
                    className="accent-[#1E8F8E]"
                  />
                  Show a Download button on the shared page
                </label>
              )}
              <p className="mt-2 text-xs text-[var(--text-2)]">
                Anyone with this link can view {kind === "doc" ? "the document" : "the video"} — no
                login needed.
                {kind === "video" && !allowDownload && " Viewers can watch but won’t see a download option."}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
