import type { ReactNode } from "react";

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent ${className}`}
    />
  );
}

type Tone = "green" | "amber" | "red" | "violet" | "zinc";

const TONES: Record<Tone, string> = {
  green: "bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/20",
  amber: "bg-amber-500/15 text-amber-300 ring-1 ring-inset ring-amber-500/20",
  red: "bg-red-500/15 text-red-300 ring-1 ring-inset ring-red-500/20",
  violet: "bg-violet-500/15 text-violet-300 ring-1 ring-inset ring-violet-500/20",
  zinc: "bg-zinc-500/10 text-zinc-400 ring-1 ring-inset ring-zinc-500/20",
};

export function Badge({ tone = "zinc", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge ${TONES[tone]}`}>{children}</span>;
}

const DOTS: Record<string, string> = {
  done: "bg-emerald-500",
  running: "bg-amber-400 animate-pulse",
  error: "bg-red-500",
  pending: "bg-zinc-600",
};

export function StatusDot({ status }: { status?: string }) {
  return <span className={`h-2 w-2 rounded-full ${DOTS[status ?? "pending"] ?? DOTS.pending}`} />;
}

export function ComingSoon({
  title,
  desc,
  track,
}: {
  title: string;
  desc: string;
  track?: string;
}) {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      <div className="card flex flex-col items-center px-6 py-16 text-center">
        <span className="badge mb-4 bg-violet-500/15 text-violet-300 ring-1 ring-inset ring-violet-500/20">
          Coming in V2
        </span>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-2 max-w-md text-sm text-zinc-500">{desc}</p>
        {track && (
          <p className="mt-4 text-xs text-zinc-600">
            Planned as <span className="text-zinc-400">{track}</span> in V2-DEVELOPMENT-PLAN.md
          </p>
        )}
      </div>
    </main>
  );
}

export function EmptyState({
  icon,
  title,
  hint,
}: {
  icon?: ReactNode;
  title: string;
  hint?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-[var(--border-strong)] bg-[var(--card)] px-6 py-14 text-center">
      {icon && <div className="mb-3 text-[var(--text-3)]">{icon}</div>}
      <p className="text-sm font-medium text-[var(--text)]">{title}</p>
      {hint && <p className="mt-1 max-w-sm text-sm text-[var(--text-2)]">{hint}</p>}
    </div>
  );
}
