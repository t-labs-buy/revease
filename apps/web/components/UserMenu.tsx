"use client";

/** The account avatar in the top bar. Click it for who you're signed in as, a
 *  link to Account, and Sign out. */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";

/** Initials for the avatar — from the name, else the email local part. */
function initials(name: string, email: string): string {
  const source = name.trim() || email.split("@")[0] || "?";
  const parts = source.split(/[\s._-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : source.slice(0, 2)).toUpperCase();
}

export function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Close on an outside click or Escape — the usual expectations for a menu.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;

  return (
    <div ref={rootRef} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={user.email}
        className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-[#7C3AED] to-[#A78BFA] text-sm font-semibold text-white transition-transform hover:scale-105"
      >
        {initials(user.name, user.email)}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-2 w-60 overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-2xl shadow-black/20"
        >
          <div className="flex items-center gap-2.5 border-b border-[var(--border)] px-3.5 py-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#7C3AED] to-[#A78BFA] text-xs font-semibold text-white">
              {initials(user.name, user.email)}
            </span>
            <span className="min-w-0">
              <span className="block truncate text-[13px] font-semibold leading-tight text-[var(--text)]">
                {user.name || user.email.split("@")[0]}
              </span>
              <span className="block truncate text-[11px] leading-tight text-[var(--text-3)]">
                {user.email}
              </span>
            </span>
          </div>

          <div className="p-1.5">
            <Link
              href="/account"
              role="menuitem"
              onClick={() => setOpen(false)}
              className="block rounded-xl px-3 py-2 text-[13px] text-[var(--text-2)] transition-colors hover:bg-[var(--hover)] hover:text-[var(--text)]"
            >
              Account settings
            </Link>
            <button
              role="menuitem"
              onClick={() => {
                setOpen(false);
                logout();
              }}
              className="block w-full rounded-xl px-3 py-2 text-left text-[13px] text-red-500 transition-colors hover:bg-red-500/10"
            >
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
