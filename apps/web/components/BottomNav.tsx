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

  return (
    <div
      className="fixed right-5 top-1/2 z-50 -translate-y-1/2"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      {/* expanded menu — absolutely positioned so it never shifts the collapsed handle off-center.
          The outer element closes the visual gap to the button with padding (not margin), so that
          gap stays part of its hit area and the pointer never crosses "dead" space that would
          trigger mouseleave on the wrapper mid-hover. */}
      <div className="absolute bottom-full right-0 w-[168px] pb-2">
        <div
          className={`flex flex-col items-stretch gap-1 rounded-[22px] border border-[var(--border)] bg-[var(--card)] p-2.5 shadow-2xl shadow-black/20 transition-all duration-200 ${
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
      </div>

      {/* collapsed handle — always visible. Clicking it goes straight home; hovering the
          wrapper still reveals the flyout for the other nav links. */}
      <Link
        href="/"
        onClick={() => setOpen(false)}
        title="Home"
        className="flex items-center rounded-full border border-[var(--border)] bg-[var(--card)] p-3 shadow-xl shadow-black/20"
      >
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-[#6d5dfb] to-[#a855f7] text-white">
          <IconHome width={22} height={22} />
        </span>
      </Link>
    </div>
  );
}
