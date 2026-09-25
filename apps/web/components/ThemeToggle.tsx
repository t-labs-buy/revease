"use client";

import { useEffect, useState } from "react";
import { IconMoon, IconSun } from "@/components/icons";

export function ThemeToggle({ compact }: { compact?: boolean }) {
  const [dark, setDark] = useState(false);

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

  const icon = dark ? <IconSun width={17} height={17} /> : <IconMoon width={17} height={17} />;

  if (compact) {
    return (
      <button
        onClick={toggle}
        aria-label={dark ? "Switch to light" : "Switch to dark"}
        title={dark ? "Switch to light" : "Switch to dark"}
        className="flex h-9 w-9 items-center justify-center rounded-lg text-[var(--text-2)] transition-colors hover:bg-[var(--hover)] hover:text-[var(--text)]"
      >
        {icon}
      </button>
    );
  }

  return (
    <button
      onClick={toggle}
      className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-[var(--text-2)] transition-colors hover:bg-[var(--hover)] hover:text-[var(--text)]"
    >
      <span className="text-[var(--text-3)]">{icon}</span>
      {dark ? "Light mode" : "Dark mode"}
    </button>
  );
}
