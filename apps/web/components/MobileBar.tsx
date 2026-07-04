"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "@/components/ThemeToggle";

export function MobileBar() {
  const pathname = usePathname();
  if (pathname.startsWith("/share/")) return null;
  return (
    <div className="flex h-14 items-center border-b border-[var(--border)] px-6 md:hidden">
      <Link href="/" className="flex items-center gap-2">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-[#6d5dfb] to-[#a855f7] text-sm font-bold text-white">
          R
        </span>
        <span className="font-semibold tracking-tight">RevEase</span>
      </Link>
      <div className="ml-auto">
        <ThemeToggle compact />
      </div>
    </div>
  );
}
