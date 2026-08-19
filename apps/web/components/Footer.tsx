"use client";

import { usePathname } from "next/navigation";

// Public share viewer has no app chrome — keep the footer out of it too.
const HIDE_ON = [/^\/share\//];

export function Footer() {
  const pathname = usePathname();
  if (HIDE_ON.some((re) => re.test(pathname))) return null;

  return (
    // The rule spans the page; the content inside it stays on the app's grid.
    // Putting both on one element drew the line only across the content box.
    <footer className="mt-auto w-full border-t border-[var(--border)]">
      <div className="mx-auto flex w-full max-w-[1600px] flex-col items-center gap-3 px-8 py-6 text-sm text-[var(--text-2)] sm:flex-row sm:justify-between">
        <span>© {new Date().getFullYear()} RevEase. All rights reserved.</span>
        <span className="flex items-center gap-2.5">
          <span className="text-[var(--text-3)]">Powered by</span>
          <span className="flex items-center rounded-lg bg-white px-2.5 py-1.5 ring-1 ring-black/5">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/tarento-logo.svg" alt="Tarento" className="h-5 w-auto" />
          </span>
        </span>
      </div>
    </footer>
  );
}
