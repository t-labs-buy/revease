"use client";

import { useEffect, useState } from "react";

export function ThemeToggle({ compact }: { compact?: boolean }) {
  const [dark, setDark] = useState(true);

  useEffect(() => {
    setDark(document.documentElement.classList.contains("dark"));
  }, []);

  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("theme", next ? "dark" : "light");
    } catch {
      /* ignore */
    }
  };

  if (compact) {
    return (
      <button
        onClick={toggle}
        title={dark ? "Switch to light" : "Switch to dark"}
        className="flex h-9 w-9 items-center justify-center rounded-xl border border-[var(--border)] bg-[var(--card)] text-[var(--text-2)] transition-colors hover:text-[var(--text)]"
      >
        {dark ? "☀" : "🌙"}
      </button>
    );
  }

  return (
    <button
      onClick={toggle}
      className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-[var(--text-2)] transition-colors hover:bg-[var(--hover)] hover:text-[var(--text)]"
    >
      <span className="text-[var(--text-3)]">{dark ? "☀" : "🌙"}</span>
      {dark ? "Light mode" : "Dark mode"}
    </button>
  );
}
