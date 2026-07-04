"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { IconBook, IconHome, IconLibrary, IconSkills } from "@/components/icons";
import { ThemeToggle } from "@/components/ThemeToggle";

const NAV = [
  { href: "/", label: "Home", icon: IconHome, match: (p: string) => p === "/" },
  { href: "/skills", label: "Skills", icon: IconSkills },
  { href: "/library", label: "Library", icon: IconLibrary },
  { href: "/knowledge-base", label: "Knowledge Base", icon: IconBook },
];

function NavItem({
  href,
  active,
  icon,
  children,
}: {
  href: string;
  active: boolean;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors duration-150 ${
        active
          ? "bg-[#6d5dfb]/15 text-[var(--text)]"
          : "text-[var(--text-2)] hover:bg-[var(--hover)] hover:text-[var(--text)]"
      }`}
    >
      <span className={active ? "text-[var(--brand-2)]" : "text-[var(--text-3)]"}>{icon}</span>
      {children}
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  if (pathname.startsWith("/share/")) return null; // public viewer — no app chrome

  return (
    <aside className="sticky top-0 hidden h-screen w-[230px] flex-none flex-col border-r border-[var(--border)] bg-[var(--panel)] px-3 py-5 md:flex">
      <Link href="/" className="mb-7 flex items-center gap-2.5 px-2">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-[#6d5dfb] to-[#a855f7] text-base font-bold text-white shadow-lg shadow-[#6d5dfb]/30">
          R
        </span>
        <span className="text-[17px] font-semibold tracking-tight text-[var(--text)]">RevEase</span>
      </Link>

      <nav className="flex flex-col gap-1">
        {NAV.map(({ href, label, icon: Icon, match }) => {
          const active = match ? match(pathname) : pathname.startsWith(href);
          return (
            <NavItem key={href} href={href} active={active} icon={<Icon />}>
              {label}
            </NavItem>
          );
        })}
      </nav>

      <div className="mt-auto flex flex-col gap-1">
        <ThemeToggle />
        <button
          className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-[var(--text-2)] transition-colors hover:bg-[var(--hover)] hover:text-[var(--text)]"
          title="Settings (coming soon)"
        >
          <span className="text-[var(--text-3)]">⚙</span> Settings
        </button>
        <div className="mt-1 flex items-center gap-2.5 rounded-xl border border-[var(--border)] bg-[var(--card)] px-2.5 py-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-[#6d5dfb] to-[#a855f7] text-xs font-semibold text-white">
            U
          </span>
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-[var(--text)]">User</div>
            <div className="truncate text-[11px] text-[var(--text-3)]">Pro Plan</div>
          </div>
        </div>
      </div>
    </aside>
  );
}
