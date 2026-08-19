import type { ReactNode } from "react";

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      className={`inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent ${className}`}
    />
  );
}

type Tone = "green" | "amber" | "red" | "violet" | "zinc";

// 500-level text reads on both themes; the 300s these used to carry were tuned
// for the dark build and washed out to near-invisible on the light background.
const TONES: Record<Tone, string> = {
  green: "bg-emerald-500/10 text-emerald-500 ring-1 ring-inset ring-emerald-500/25",
  amber: "bg-amber-500/10 text-amber-600 ring-1 ring-inset ring-amber-500/25",
  red: "bg-red-500/10 text-red-500 ring-1 ring-inset ring-red-500/25",
  violet: "bg-[#7C3AED]/10 text-[#7C3AED] ring-1 ring-inset ring-[#7C3AED]/25",
  zinc: "bg-[var(--text-3)]/10 text-[var(--text-2)] ring-1 ring-inset ring-[var(--border-strong)]",
};

export function Badge({ tone = "zinc", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge ${TONES[tone]}`}>{children}</span>;
}

const DOTS: Record<string, string> = {
  done: "bg-emerald-500",
  running: "bg-amber-400 animate-pulse",
  error: "bg-red-500",
  pending: "bg-[var(--text-3)]",
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
        <span className="badge mb-4 bg-[#7C3AED]/10 text-[#7C3AED] ring-1 ring-inset ring-[#7C3AED]/25">
          Coming in V2
        </span>
        <h1 className="text-2xl font-semibold tracking-tight text-[var(--text)]">{title}</h1>
        <p className="mt-2 max-w-md text-sm text-[var(--text-2)]">{desc}</p>
        {track && (
          <p className="mt-4 text-xs text-[var(--text-3)]">
            Planned as <span className="text-[var(--text-2)]">{track}</span> in
            V2-DEVELOPMENT-PLAN.md
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
