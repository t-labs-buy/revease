"use client";

/**
 * The app's primary navigation: a fixed navy sidebar (Tarento palette). Navy is
 * the *structure* colour; teal is reserved for the single active item so the
 * eye has one place to land. Everything the old top-nav carried — the brand,
 * the nav tabs, admin links — lives here now; the header only keeps search,
 * notifications and the account menu.
 *
 * It collapses to an icon-only rail (toggle at the bottom, or ⌘/Ctrl+B). The
 * choice is remembered in localStorage and read after mount, so a hard reload
 * briefly shows the expanded state — the alternative (reading storage during
 * render) trips React's hydration check.
 *
 * Shelved features stay listed but inert with a small "Beta" pill instead of a
 * "Coming soon" overlay, so the product doesn't advertise what it can't do yet.
 */

import { Suspense, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  IconBook,
  IconChart,
  IconChevronLeft,
  IconChevronRight,
  IconDoc,
  IconFolder,
  IconHelp,
  IconHome,
  IconLibrary,
  IconSettings,
  IconUsers,
  IconVideo,
} from "@/components/icons";
import { useAuth } from "@/contexts/AuthContext";

// The public share viewer and the auth screens get no app chrome.
const HIDE_ON = [/^\/share\//, /^\/login$/, /^\/register$/];

const STORAGE_KEY = "revease.sidebar";

interface Item {
  href: string;
  label: string;
  icon: (p: React.SVGProps<SVGSVGElement>) => JSX.Element;
  /** Exact match on the path + query. Defaults to a prefix match on the path. */
  exact?: boolean;
  soon?: boolean;
  adminOnly?: boolean;
}

const MAIN: Item[] = [
  { href: "/", label: "Home", icon: IconHome, exact: true },
  { href: "/library", label: "Projects", icon: IconFolder, exact: true },
  { href: "/library?kind=video", label: "Videos", icon: IconVideo, exact: true },
  { href: "/library?kind=document", label: "Documents", icon: IconDoc, exact: true },
  { href: "/library/packages", label: "Library", icon: IconLibrary },
  { href: "/knowledge-base", label: "Knowledge Base", icon: IconBook, soon: true },
];

const ADMIN: Item[] = [
  { href: "/admin/usage", label: "Usage", icon: IconChart, adminOnly: true },
  { href: "/admin/users", label: "Users", icon: IconUsers, adminOnly: true },
];

const FOOT: Item[] = [
  { href: "/account", label: "Settings", icon: IconSettings },
  { href: "/help", label: "Help", icon: IconHelp, soon: true },
];

function NavItem({ item, active, collapsed }: { item: Item; active: boolean; collapsed: boolean }) {
  const Icon = item.icon;
  const inner = (
    <>
      <Icon width={16} height={16} className="flex-none" />
      {!collapsed && <span className="truncate">{item.label}</span>}
      {!collapsed && item.soon && (
        <span className="ml-auto rounded bg-white/10 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-white/60">
          Beta
        </span>
      )}
    </>
  );
  const cls = `flex items-center gap-3 rounded-lg text-[13.5px] font-medium transition-colors duration-150 ${
    collapsed ? "justify-center px-0 py-2.5" : "px-3 py-2"
  }`;
  // When collapsed the label is gone, so the tooltip carries it.
  const title = collapsed ? (item.soon ? `${item.label} (Beta)` : item.label) : undefined;
  if (item.soon)
    return (
      <span aria-disabled="true" title={title} className={`${cls} cursor-default select-none text-white/45`}>
        {inner}
      </span>
    );
  return (
    <Link
      href={item.href}
      title={title}
      aria-label={collapsed ? item.label : undefined}
      className={`${cls} ${
        active ? "bg-[var(--brand)] text-white" : "text-white/75 hover:bg-white/[0.07] hover:text-white"
      }`}
    >
      {inner}
    </Link>
  );
}

function Group({ title, collapsed, children }: { title?: string; collapsed: boolean; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      {title &&
        (collapsed ? (
          <div className="mx-2 mb-1.5 border-t border-white/10" />
        ) : (
          <div className="mb-1.5 px-3 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-white/35">{title}</div>
        ))}
      {children}
    </div>
  );
}

function SidebarInner() {
  const pathname = usePathname();
  const search = useSearchParams();
  const { user, isAdmin } = useAuth();
  const [collapsed, setCollapsed] = useState(false);

  // Restore the remembered state after mount (see module docstring).
  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(STORAGE_KEY) === "collapsed");
    } catch {
      /* storage unavailable: stay expanded */
    }
  }, []);

  const toggle = () => {
    setCollapsed((v) => {
      const next = !v;
      try {
        localStorage.setItem(STORAGE_KEY, next ? "collapsed" : "expanded");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  // ⌘B / Ctrl+B toggles, matching the editor convention people already know.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (HIDE_ON.some((re) => re.test(pathname))) return null;
  if (!user) return null;

  const current = search.toString() ? `${pathname}?${search.toString()}` : pathname;
  const isActive = (item: Item) => (item.exact ? current === item.href : pathname.startsWith(item.href));

  return (
    <aside
      data-collapsed={collapsed ? "true" : undefined}
      className={`sticky top-0 hidden h-screen flex-none flex-col bg-[var(--navy)] py-5 transition-[width] duration-200 ease-out md:flex ${
        collapsed ? "w-[68px] px-2.5" : "w-[240px] px-3"
      }`}
    >
      <Link
        href="/"
        title={collapsed ? "RevEase by Tarento" : undefined}
        className={`mb-6 block ${collapsed ? "mx-auto" : "px-3"}`}
      >
        {collapsed ? (
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/[0.06] text-[17px] font-bold leading-none tracking-tight text-white">
            R<span className="text-[var(--brand-2)]">E</span>
          </span>
        ) : (
          <>
            <span className="block text-[20px] font-bold leading-none tracking-tight text-white">
              Rev<span className="text-[var(--brand-2)]">Ease</span>
            </span>
            <span className="mt-1.5 block text-[11px] font-medium tracking-wide text-white/45">by Tarento</span>
          </>
        )}
      </Link>

      <nav className="flex flex-col gap-6">
        <Group collapsed={collapsed}>
          {MAIN.map((item) => (
            <NavItem key={item.href} item={item} active={isActive(item)} collapsed={collapsed} />
          ))}
        </Group>
        {isAdmin && (
          <Group title="Admin" collapsed={collapsed}>
            {ADMIN.map((item) => (
              <NavItem key={item.href} item={item} active={isActive(item)} collapsed={collapsed} />
            ))}
          </Group>
        )}
      </nav>

      <div className="mt-auto flex flex-col gap-0.5 border-t border-white/10 pt-4">
        {FOOT.map((item) => (
          <NavItem key={item.href} item={item} active={isActive(item)} collapsed={collapsed} />
        ))}
        <button
          onClick={toggle}
          aria-expanded={!collapsed}
          title={collapsed ? "Expand sidebar (⌘B)" : "Collapse sidebar (⌘B)"}
          className={`mt-1 flex items-center gap-3 rounded-lg text-[13.5px] font-medium text-white/60 transition-colors hover:bg-white/[0.07] hover:text-white ${
            collapsed ? "justify-center px-0 py-2.5" : "px-3 py-2"
          }`}
        >
          {collapsed ? (
            <IconChevronRight width={16} height={16} className="flex-none" />
          ) : (
            <>
              <IconChevronLeft width={16} height={16} className="flex-none" />
              <span>Collapse</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}

/** useSearchParams needs a Suspense boundary so the rest of the layout can still prerender. */
export function Sidebar() {
  return (
    <Suspense fallback={<aside className="hidden h-screen w-[240px] flex-none bg-[var(--navy)] md:block" />}>
      <SidebarInner />
    </Suspense>
  );
}
