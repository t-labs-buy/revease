"use client";

/**
 * The app's shared header: brand, primary nav, notifications and the account
 * avatar. It lives in the root layout, so every signed-in page gets it — which
 * is what makes Sign out reachable from anywhere.
 *
 * The centre of the bar is a *slot*: pages that own a search box (the dashboard)
 * portal theirs into it via `useTopBarSlot`, so the header stays shared without
 * having to know about any one page's state.
 */

import { createContext, useContext, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconBell } from "@/components/icons";
import { ThemeToggle } from "@/components/ThemeToggle";
import { UserMenu } from "@/components/UserMenu";
import { useAuth } from "@/contexts/AuthContext";

// `soon` renders the tab dimmed and inert with a "Soon" pill. The page behind it
// still exists and works — flip the flag off to bring it back.
const NAV = [
  { label: "Home", href: "/" },
  { label: "Library", href: "/library" },
  { label: "Knowledge Base", href: "/knowledge-base", soon: true },
];

// The public share viewer and the auth screens get no app chrome.
const HIDE_ON = [/^\/share\//, /^\/login$/, /^\/register$/];

interface SlotState {
  slot: HTMLDivElement | null;
  setSlot: (el: HTMLDivElement | null) => void;
}

const TopBarContext = createContext<SlotState | null>(null);

export function TopBarProvider({ children }: { children: React.ReactNode }) {
  const [slot, setSlot] = useState<HTMLDivElement | null>(null);
  const value = useMemo(() => ({ slot, setSlot }), [slot]);
  return <TopBarContext.Provider value={value}>{children}</TopBarContext.Provider>;
}

/** The header's centre element, or null before it mounts (or where it's hidden).
 *  Portal into it to put page-specific controls in the shared bar. */
export function useTopBarSlot(): HTMLDivElement | null {
  return useContext(TopBarContext)?.slot ?? null;
}

const isActive = (pathname: string, href: string) =>
  href === "/" ? pathname === "/" : pathname.startsWith(href);

export function TopBar() {
  const pathname = usePathname();
  const { user } = useAuth();
  const context = useContext(TopBarContext);

  if (HIDE_ON.some((re) => re.test(pathname))) return null;
  if (!user) return null; // signed out: the login screen is the whole UI

  return (
    <header className="sticky top-0 z-20 flex items-center gap-6 border-b border-[var(--border)] bg-[var(--bg)]/85 px-8 py-3 backdrop-blur-md">
      <Link href="/" className="flex items-center gap-2.5">
        <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-[#7C3AED] to-[#A78BFA] text-base font-bold text-white shadow-sm shadow-[#7C3AED]/30">
          R
        </span>
        <span className="text-[17px] font-semibold tracking-tight text-[var(--text)]">
          RevEase
        </span>
      </Link>

      <nav className="hidden items-center gap-1 md:flex">
        {NAV.map((n) =>
          n.soon ? (
            <span
              key={n.href}
              aria-disabled="true"
              className="select-none rounded-full px-4 py-2 text-sm font-medium text-[var(--text-3)] opacity-45"
            >
              {n.label}
            </span>
          ) : (
            <Link
              key={n.href}
              href={n.href}
              className={`rounded-full px-4 py-2 text-sm font-medium transition-colors duration-200 ${
                isActive(pathname, n.href)
                  ? "bg-[#7C3AED]/10 text-[#7C3AED]"
                  : "text-[var(--text-2)] hover:bg-[var(--hover)] hover:text-[var(--text)]"
              }`}
            >
              {n.label}
            </Link>
          ),
        )}
      </nav>

      {/* page-owned controls land here (see useTopBarSlot) */}
      <div ref={context?.setSlot} className="relative ml-auto w-full max-w-xl" />

      <div className="flex items-center gap-2.5">
        <ThemeToggle compact />
        <button
          aria-label="Notifications"
          className="relative flex h-10 w-10 items-center justify-center rounded-full border border-[var(--border)] bg-[var(--card)] text-[var(--text-2)] transition-colors hover:text-[var(--text)]"
        >
          <IconBell width={17} height={17} />
          <span className="absolute right-2.5 top-2 h-1.5 w-1.5 rounded-full bg-[#EC4899]" />
        </button>
        <UserMenu />
      </div>
    </header>
  );
}
