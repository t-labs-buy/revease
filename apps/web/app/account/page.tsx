"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { getToken } from "@/lib/auth";
import { absoluteApiBase, API_BASE } from "@/lib/api";

export default function AccountPage() {
  const { user, logout } = useAuth();
  const [revealed, setRevealed] = useState(false);
  const [copied, setCopied] = useState<"base" | "token" | null>(null);
  // Resolved after mount: the deployed base is origin-relative ("/api"), and the
  // extension is a separate client that can only use an absolute URL.
  const [apiBase, setApiBase] = useState(API_BASE);
  useEffect(() => setApiBase(absoluteApiBase()), []);

  if (!user) return null; // AuthGate already handles the signed-out case

  const token = getToken() ?? "";

  const copy = async (what: "base" | "token", value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(what);
      setTimeout(() => setCopied(null), 1800);
    } catch {
      /* clipboard blocked — the field is selectable as a fallback */
    }
  };

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight text-[var(--text)]">Account</h1>
      <p className="mt-1.5 text-sm text-[var(--text-2)]">
        Everything you record, generate and save is private to this account.
      </p>

      <section className="card mt-6 p-5">
        <h2 className="text-sm font-semibold text-[var(--text)]">Signed in as</h2>
        <dl className="mt-3 space-y-2 text-sm">
          <div className="flex justify-between gap-4">
            <dt className="text-[var(--text-2)]">Name</dt>
            <dd className="text-[var(--text)]">{user.name || "—"}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-[var(--text-2)]">Email</dt>
            <dd className="truncate text-[var(--text)]">{user.email}</dd>
          </div>
        </dl>
        <button onClick={logout} className="btn btn-secondary btn-sm mt-4">
          Sign out
        </button>
      </section>

      {/* The extension is a separate client, so it needs its own copy of the
          token — it can't read this app's localStorage. */}
      <section className="card mt-4 p-5">
        <h2 className="text-sm font-semibold text-[var(--text)]">Connect extension</h2>
        <p className="mt-1.5 text-sm text-[var(--text-2)]">
          Paste these into the RevEase browser extension (popup or Auto Record side panel) so
          it records into your space.
        </p>

        <label className="mt-4 block text-xs font-semibold uppercase tracking-wider text-[var(--text-3)]">
          API base
        </label>
        <div className="mt-1.5 flex gap-2">
          <input readOnly value={apiBase} className="input font-mono text-xs" />
          <button
            onClick={() => void copy("base", apiBase)}
            className="btn btn-secondary btn-sm shrink-0"
          >
            {copied === "base" ? "Copied" : "Copy"}
          </button>
        </div>

        <label className="mt-4 block text-xs font-semibold uppercase tracking-wider text-[var(--text-3)]">
          Access token
        </label>
        <div className="mt-1.5 flex gap-2">
          <input
            readOnly
            type={revealed ? "text" : "password"}
            value={token}
            className="input font-mono text-xs"
          />
          <button
            onClick={() => setRevealed((v) => !v)}
            className="btn btn-secondary btn-sm shrink-0"
          >
            {revealed ? "Hide" : "Show"}
          </button>
          <button
            onClick={() => void copy("token", token)}
            className="btn btn-primary btn-sm shrink-0"
          >
            {copied === "token" ? "Copied" : "Copy"}
          </button>
        </div>
        <p className="mt-2.5 text-xs text-[var(--text-3)]">
          Treat this like a password — anyone holding it can act as you. Signing out here
          doesn&apos;t revoke it, so paste a fresh one into the extension if you ever share a
          machine.
        </p>
      </section>

      <section className="card mt-4 p-5">
        <h2 className="text-sm font-semibold text-[var(--text)]">Password</h2>
        <p className="mt-1.5 text-sm text-[var(--text-2)]">
          Changing and resetting your password isn&apos;t available yet — it needs an email
          service this deployment doesn&apos;t have configured.
        </p>
      </section>
    </main>
  );
}
