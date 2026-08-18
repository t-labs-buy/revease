"use client";

/**
 * Whole-app route guard. It wraps the layout rather than individual pages, so a
 * new page is private by default — you have to add it to PUBLIC_ROUTES to expose
 * it, which is the safe direction for a mistake to go.
 *
 * The server can't be fooled by getting past this: every private endpoint checks
 * the token independently. This is here so signed-out visitors get a login screen
 * instead of a page full of failed requests.
 */

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { Spinner } from "@/components/ui";

/** Routes reachable without an account: the auth screens themselves, and the
 *  public share viewer (whose whole purpose is to work for anonymous visitors). */
const PUBLIC_ROUTES = [/^\/login$/, /^\/register$/, /^\/share\//];

const isPublic = (pathname: string) => PUBLIC_ROUTES.some((re) => re.test(pathname));

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const publicRoute = isPublic(pathname);

  useEffect(() => {
    if (loading) return;
    if (!user && !publicRoute) {
      // Remember where they were headed so login can return them there.
      const next = pathname && pathname !== "/" ? `?next=${encodeURIComponent(pathname)}` : "";
      router.replace(`/login${next}`);
    }
    if (user && (pathname === "/login" || pathname === "/register")) {
      router.replace("/");
    }
  }, [user, loading, publicRoute, pathname, router]);

  if (publicRoute) return <>{children}</>;

  // Resolving the token, or mid-redirect: show a placeholder rather than a
  // flash of signed-in UI that is about to be replaced.
  if (loading || !user) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center text-[var(--text-3)]">
        <Spinner />
      </div>
    );
  }

  return <>{children}</>;
}
