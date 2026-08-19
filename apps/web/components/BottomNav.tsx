"use client";

/** A floating shortcut back to the dashboard. Nav links, the theme toggle and
 *  the account menu all live in the shared TopBar, so this is just the button. */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconHome } from "@/components/icons";
import { useAuth } from "@/contexts/AuthContext";

// The public share viewer and the auth screens have no app chrome.
const HIDE_ON = [/^\/share\//, /^\/login$/, /^\/register$/];

export function BottomNav() {
  const pathname = usePathname();
  const { user } = useAuth();
  if (HIDE_ON.some((re) => re.test(pathname))) return null;
  if (!user) return null;

  return (
    <Link
      href="/"
      title="Home"
      className="hidden fixed right-5 top-1/2 z-50 -translate-y-1/2 items-center rounded-full border border-[var(--border)] bg-[var(--card)] p-3 shadow-xl shadow-black/20"
    >
      <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-[#6d5dfb] to-[#a855f7] text-white">
        <IconHome width={22} height={22} />
      </span>
    </Link>
  );
}
