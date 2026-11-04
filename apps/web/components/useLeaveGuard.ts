"use client";

/**
 * Stop an in-app link from silently throwing away unsaved edits.
 *
 * Why a document-level click listener instead of wrapping each <Link>: the
 * editor can be left through its own back arrow, the Document link, the
 * sidebar, the user menu… any of them would drop the edits. Listening in the
 * capture phase on `document` sees every same-origin anchor click before
 * Next's <Link> handler does, so one guard covers links that live outside the
 * page component too.
 *
 * A closed tab / reload / typed URL goes through `beforeunload`, where browsers
 * only allow their own generic prompt.
 *
 * Known gap: the browser's own Back button in an SPA fires `popstate` after the
 * URL has already changed, and Next's router has no supported way to veto it.
 * Faking a history entry to trap it fights the router's own state, so it is
 * deliberately not done here.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

export function useLeaveGuard(dirty: boolean) {
  const router = useRouter();
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  const [pendingHref, setPendingHref] = useState<string | null>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (!dirtyRef.current) return;
      // let the browser handle new-tab / download style clicks: nothing is lost
      if (e.defaultPrevented || e.button !== 0) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!a || a.hasAttribute("download")) return;
      if (a.target && a.target !== "_self") return;
      let url: URL;
      try {
        url = new URL(a.href, window.location.href);
      } catch {
        return;
      }
      if (url.origin !== window.location.origin) return;
      // same page (e.g. a #hash jump) does not leave the editor
      if (url.pathname === window.location.pathname && url.search === window.location.search)
        return;
      e.preventDefault();
      e.stopPropagation();
      setPendingHref(url.pathname + url.search + url.hash);
    };
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!dirtyRef.current) return;
      e.preventDefault();
      e.returnValue = "";
    };
    document.addEventListener("click", onClick, true);
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, []);

  const stay = useCallback(() => setPendingHref(null), []);
  const leave = useCallback(() => {
    const href = pendingHref;
    setPendingHref(null);
    if (href) router.push(href);
  }, [pendingHref, router]);

  return { pendingHref, stay, leave };
}
