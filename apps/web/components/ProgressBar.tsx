"use client";

/** Shared progress primitives: a determinate bar (indeterminate when the value
 *  is unknown) and human durations for elapsed/ETA copy. */

export function ProgressBar({ value, className = "", tone = "brand" }: { value: number | null | undefined; className?: string; tone?: "brand" | "warn" | "error" }) {
  const color = tone === "error" ? "bg-[var(--error)]" : tone === "warn" ? "bg-[var(--warning)]" : "bg-[var(--brand)]";
  const known = typeof value === "number" && Number.isFinite(value);
  const pct = known ? Math.round(Math.min(1, Math.max(0, value!)) * 100) : null;
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct ?? undefined}
      className={`relative h-1.5 overflow-hidden rounded-full bg-[var(--hover)] ${className}`}
    >
      {known ? (
        <div className={`h-full rounded-full ${color} transition-[width] duration-700 ease-out`} style={{ width: `${pct}%` }} />
      ) : (
        <div className={`absolute inset-y-0 w-1/3 animate-[indeterminate_1.4s_ease-in-out_infinite] rounded-full ${color}`} />
      )}
    </div>
  );
}

export function humanDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}
