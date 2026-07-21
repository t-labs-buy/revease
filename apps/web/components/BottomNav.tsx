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
      className="fixed right-5 top-1/2 z-50 -translate-y-1/2"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      {/* expanded menu — absolutely positioned so it never shifts the collapsed handle off-center */}
      <div
        className={`absolute bottom-full right-0 mb-2 flex w-[168px] flex-col items-stretch gap-1 rounded-[22px] border border-[var(--border)] bg-[var(--card)] p-2.5 shadow-2xl shadow-black/20 transition-all duration-200 ${
          open ? "translate-x-0 opacity-100" : "pointer-events-none translate-x-3 opacity-0"
        }`}
      >
        {NAV.map(({ href, label, icon: Icon, match }) => {
          const on = match ? match(pathname) : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              onClick={() => setOpen(false)}
              className={`flex items-center gap-2.5 rounded-2xl px-3 py-2 transition-colors ${
                on ? "bg-[var(--hover)]" : "hover:bg-[var(--hover)]"
              }`}
            >
              <span className={on ? "text-[var(--text)]" : "text-[var(--text-3)]"}>
                <Icon width={20} height={20} />
              </span>
              <span
                className={`text-[13px] leading-tight ${
                  on ? "font-semibold text-[var(--text)]" : "text-[var(--text-3)]"
                }`}
              >
                {label}
              </span>
            </Link>
          );
        })}
        <div className="flex items-center gap-2.5 px-3 py-2">
          <ThemeToggle compact />
        </div>
      </div>

      {/* collapsed handle — always visible */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2.5 rounded-full border border-[var(--border)] bg-[var(--card)] px-5 py-2 shadow-xl shadow-black/20"
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
