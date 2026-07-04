"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { IconBook, IconHome, IconLibrary, IconSkills } from "@/components/icons";
import { ThemeToggle } from "@/components/ThemeToggle";

const NAV = [
  { href: "/", label: "Home", icon: IconHome, match: (p: string) => p === "/" },
  { href: "/skills", label: "Skills", icon: IconSkills },
  { href: "/library", label: "Library", icon: IconLibrary },
  { href: "/knowledge-base", label: "Knowledge Base", icon: IconBook },
];

// Only the public share viewer hides the app nav.
const HIDE_ON = [/^\/share\//];

export function BottomNav() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  if (HIDE_ON.some((re) => re.test(pathname))) return null;

  const active = NAV.find((n) => (n.match ? n.match(pathname) : pathname.startsWith(n.href))) ?? NAV[0];

  return (
    <div
      className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      {/* expanded menu */}
      <div
        className={`mb-2 flex items-end gap-1 rounded-[26px] border border-[var(--border)] bg-[var(--card)] p-2.5 shadow-2xl shadow-black/20 transition-all duration-200 ${
          open ? "translate-y-0 opacity-100" : "pointer-events-none translate-y-3 opacity-0"
        }`}
      >
        {NAV.map(({ href, label, icon: Icon, match }) => {
          const on = match ? match(pathname) : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              onClick={() => setOpen(false)}
              className={`flex w-[92px] flex-col items-center gap-1.5 rounded-2xl px-2 py-2.5 transition-colors ${
                on ? "bg-[var(--hover)]" : "hover:bg-[var(--hover)]"
              }`}
            >
              <span className={on ? "text-[var(--text)]" : "text-[var(--text-3)]"}>
                <Icon width={22} height={22} />
              </span>
              <span
                className={`text-center text-[11px] leading-tight ${
                  on ? "font-semibold text-[var(--text)]" : "text-[var(--text-3)]"
                }`}
              >
                {label}
              </span>
            </Link>
          );
        })}
        <div className="mx-1 flex flex-col items-center gap-1.5 px-1 py-2.5">
          <ThemeToggle compact />
        </div>
      </div>

      {/* collapsed handle — always visible */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="mx-auto flex items-center gap-2.5 rounded-full border border-[var(--border)] bg-[var(--card)] px-5 py-2 shadow-xl shadow-black/20"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-gradient-to-br from-[#6d5dfb] to-[#a855f7] text-[11px] font-bold text-white">
          R
        </span>
        <span className="text-sm font-semibold text-[var(--text)]">{active.label}</span>
        <span className="h-1 w-6 rounded-full bg-[var(--border-strong)]" />
      </button>
    </div>
  );
}
