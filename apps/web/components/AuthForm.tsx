"use client";

/** Shared chrome for the login and register screens — one card, one layout, so
 *  the two pages can't drift apart visually. */

import Link from "next/link";
import type { ReactNode } from "react";
import { Spinner } from "@/components/ui";

export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <main className="mx-auto flex min-h-[80vh] w-full max-w-md flex-col justify-center px-6 py-12">
      <div className="mb-8 text-center">
        <span className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-[#6d5dfb] to-[#a855f7] text-lg font-semibold text-white">
          R
        </span>
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--text)]">{title}</h1>
        <p className="mt-1.5 text-sm text-[var(--text-2)]">{subtitle}</p>
      </div>

      <div className="card p-6">{children}</div>

      <p className="mt-6 text-center text-sm text-[var(--text-2)]">{footer}</p>
    </main>
  );
}

export function Field({
  label,
  hint,
  ...props
}: { label: string; hint?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-[var(--text)]">{label}</span>
      <input className="input" {...props} />
      {hint && <span className="mt-1.5 block text-xs text-[var(--text-3)]">{hint}</span>}
    </label>
  );
}

export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p
      role="alert"
      className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400"
    >
      {message}
    </p>
  );
}

export function SubmitButton({ busy, children }: { busy: boolean; children: ReactNode }) {
  return (
    <button type="submit" disabled={busy} className="btn btn-primary w-full">
      {busy ? <Spinner /> : children}
    </button>
  );
}

export function AuthLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="font-medium text-[var(--brand)] hover:underline">
      {children}
    </Link>
  );
}
