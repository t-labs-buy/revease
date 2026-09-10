"use client";

/** Admin → Users: set a new password for another account.
 *
 *  There is no email transport, so the admin is the reset flow: they type a
 *  password here, the server applies it and signs the user's sessions out, and
 *  the admin passes the password on out of band. */

import { useEffect, useState } from "react";
import { resetUserPassword, type AdminUser } from "@/lib/api";

const MIN_PASSWORD = 8;

export function ResetPasswordDialog({
  user,
  onClose,
}: {
  user: AdminUser;
  onClose: () => void;
}) {
  const [password, setPassword] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard blocked — the field is selectable as a fallback */
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password.length < MIN_PASSWORD) {
      setError(`Use at least ${MIN_PASSWORD} characters`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await resetUserPassword(user.id, password);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset the password");
      setBusy(false);
    }
  };

  const who = user.name || user.email;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 p-4 backdrop-blur-[2px]"
      onClick={busy ? undefined : onClose}
    >
      <form
        onSubmit={submit}
        noValidate
        className="w-full max-w-md rounded-2xl bg-[var(--card)] p-5 shadow-2xl ring-1 ring-[var(--border)]"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-[15px] font-semibold text-[var(--text)]">Reset password</h3>
        <p className="mt-1 text-sm leading-relaxed text-[var(--text-2)]">
          Set a new password for <span className="font-medium text-[var(--text)]">{who}</span>{" "}
          ({user.email}). Their current sessions will be signed out.
        </p>

        {error && (
          <p
            role="alert"
            className="mt-3 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400"
          >
            {error}
          </p>
        )}

        <label className="mt-4 block text-xs font-semibold uppercase tracking-wider text-[var(--text-3)]">
          New password
        </label>
        <div className="mt-1.5 flex gap-2">
          <input
            type={revealed ? "text" : "password"}
            value={password}
            autoFocus
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => setPassword(e.target.value)}
            className="input font-mono text-sm"
          />
          <button
            type="button"
            onClick={() => setRevealed((v) => !v)}
            className="btn btn-secondary btn-sm shrink-0"
          >
            {revealed ? "Hide" : "Show"}
          </button>
          <button
            type="button"
            onClick={() => void copy()}
            className="btn btn-secondary btn-sm shrink-0"
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
        <p className="mt-2 text-xs text-[var(--text-3)]">At least {MIN_PASSWORD} characters.</p>

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="btn btn-secondary btn-sm"
          >
            Cancel
          </button>
          <button type="submit" disabled={busy} className="btn btn-primary btn-sm disabled:opacity-50">
            {busy ? "Resetting…" : "Reset password"}
          </button>
        </div>
      </form>
    </div>
  );
}
