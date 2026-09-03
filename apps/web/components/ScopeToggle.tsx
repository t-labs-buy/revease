"use client";

/** Admin-only pill toggle between the caller's own space ("mine") and every
 *  user's ("all"). Renders nothing for regular users — pages can include it
 *  unconditionally. */

import { useAuth } from "@/contexts/AuthContext";
import type { ListScope } from "@/lib/api";

export function ScopeToggle({
  scope,
  onChange,
  mineLabel = "Mine",
  allLabel = "Everyone's",
}: {
  scope: ListScope;
  onChange: (scope: ListScope) => void;
  mineLabel?: string;
  allLabel?: string;
}) {
  const { isAdmin } = useAuth();
  if (!isAdmin) return null;

  const options: { key: ListScope; label: string }[] = [
    { key: "mine", label: mineLabel },
    { key: "all", label: allLabel },
  ];
  return (
    <div className="flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--card)] p-1">
      {options.map((o) => (
        <button
          key={o.key}
          onClick={() => onChange(o.key)}
          className={`rounded-full px-3.5 py-1 text-sm font-medium transition-colors ${
            scope === o.key ? "bg-[#6d5dfb] text-white" : "text-[var(--text-2)] hover:text-[var(--text)]"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
