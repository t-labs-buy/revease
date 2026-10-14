"use client";

import { usePathname } from "next/navigation";

// Public share viewer has no app chrome — keep the footer out of it too. The
// video editor is a full-height workspace sized to the viewport; a footer under
// it only added a scrollbar.
const HIDE_ON = [/^\/share\//, /^\/projects\/[^/]+\/video(\/|$)/];

export function Footer() {
  const pathname = usePathname();
  if (HIDE_ON.some((re) => re.test(pathname))) return null;

  return (
    // The rule spans the page; the content inside it stays on the app's grid.
    // Putting both on one element drew the line only across the content box.
    // A fixed h-12: pages that size themselves to the viewport (the project
    // page) subtract this height, so it must not vary with wrapping.
    <footer className="mt-auto h-12 w-full border-t border-[var(--border)]">
      <div className="mx-auto flex h-full w-full max-w-[1600px] items-center justify-between gap-3 px-8 text-sm text-[var(--text-2)]">
        <span className="truncate">© {new Date().getFullYear()} RevEase. All rights reserved.</span>
        <span className="flex flex-none items-center gap-2.5">
          <span className="text-[var(--text-3)]">Powered by</span>
          <span className="flex items-center rounded-lg bg-white px-2.5 py-1 ring-1 ring-black/5">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/tarento-logo.svg" alt="Tarento" className="h-4 w-auto" />
          </span>
        </span>
      </div>
    </footer>
  );
}
