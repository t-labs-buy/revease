"use client";

import { usePathname } from "next/navigation";

// Public share viewer has no app chrome — keep the footer out of it too.
const HIDE_ON = [/^\/share\//];

export function Footer() {
  const pathname = usePathname();
  if (HIDE_ON.some((re) => re.test(pathname))) return null;

  return (
    <footer className="mx-auto flex w-full max-w-[1600px] flex-col items-center gap-3 border-t border-[var(--border)] px-8 py-7 text-sm text-black sm:flex-row sm:justify-between">
      <span className="font-semibold">© {new Date().getFullYear()} RevEase. All rights reserved.</span>
      <span className="flex items-center gap-2.5 font-semibold">
        Powered by
        <span className="flex items-center rounded-md bg-white px-3 py-2 shadow-sm ring-1 ring-black/5">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/tarento-logo.svg" alt="Tarento" className="h-6 w-auto" />
        </span>
      </span>
    </footer>
  );
}
