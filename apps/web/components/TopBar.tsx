"use client";

/**
 * The app's shared header. Navigation lives in the Sidebar; this bar keeps only
 * what belongs with the page: search, theme and the account
 * avatar (which is what makes Sign out reachable from anywhere).
 *
 * The left of the bar is a *slot*: pages that own a search box (the dashboard)
 * portal theirs into it via `useTopBarSlot`, so the header stays shared without
 * having to know about any one page's state. Below the md breakpoint the
 * sidebar is hidden, so the bar also shows the brand.
 */

import { createContext, useContext, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ActivityIndicator } from "@/components/ActivityIndicator";
import { ThemeToggle } from "@/components/ThemeToggle";
import { UserMenu } from "@/components/UserMenu";
import { useAuth } from "@/contexts/AuthContext";

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

/** The header's search element, or null before it mounts (or where it's hidden).
 *  Portal into it to put page-specific controls in the shared bar. */
export function useTopBarSlot(): HTMLDivElement | null {
  return useContext(TopBarContext)?.slot ?? null;
}

export function TopBar() {
  const pathname = usePathname();
  const { user } = useAuth();
  const context = useContext(TopBarContext);

  if (HIDE_ON.some((re) => re.test(pathname))) return null;
  if (!user) return null; // signed out: the login screen is the whole UI

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-4 border-b border-[var(--border)] bg-[var(--panel)] px-5 md:px-8">
      {/* brand shows only where the sidebar doesn't */}
      <Link href="/" className="text-[17px] font-bold tracking-tight text-[var(--navy)] md:hidden">
        Rev<span className="text-[var(--brand)]">Ease</span>
      </Link>

      {/* page-owned controls land here (see useTopBarSlot) */}
      <div ref={context?.setSlot} className="relative w-full max-w-xl" />

      <div className="ml-auto flex items-center gap-1.5">
        <ActivityIndicator />
        <ThemeToggle compact />
        <div className="ml-1.5">
          <UserMenu />
        </div>
      </div>
    </header>
  );
}
