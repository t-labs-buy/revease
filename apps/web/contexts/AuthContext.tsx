"use client";

/**
 * Holds the signed-in account for the whole app.
 *
 * On mount it resolves the stored token to an account exactly once (`/auth/me`),
 * which is also how an expired token gets discovered on a cold load. It registers
 * itself as the app's `onUnauthorized` handler, so a token that expires mid-session
 * drops the user back to /login from wherever they were.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import * as auth from "@/lib/auth";
import { onUnauthorized } from "@/lib/http";
import type { AuthUser } from "@/lib/auth";

interface AuthState {
  user: AuthUser | null;
  /** True when the signed-in account has the admin role (sees every space). */
  isAdmin: boolean;
  /** True until the stored token has been resolved — routes must wait it out
   *  rather than treating "no user yet" as "signed out". */
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  /** Creates the account only — it does not start a session, so the caller is
   *  expected to send the user on to /login. */
  register: (email: string, password: string, name: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

const isAuthRoute = (pathname: string) => pathname === "/login" || pathname === "/register";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  // Resolve the stored token once on boot.
  useEffect(() => {
    let active = true;
    auth
      .fetchMe()
      .then((me) => {
        if (active) setUser(me);
      })
      .catch(() => {
        if (active) setUser(null); // API unreachable — treat as signed out
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  // A 401 anywhere in the app means the session is gone.
  useEffect(() => {
    onUnauthorized(() => {
      setUser(null);
      // Don't navigate if they're already on an auth screen: a stale token from
      // a previous session 401s on boot, and redirecting would remount the login
      // form and wipe whatever error or input it was showing.
      if (!isAuthRoute(window.location.pathname)) router.replace("/login");
    });
    return () => onUnauthorized(null);
  }, [router]);

  const login = useCallback(async (email: string, password: string) => {
    setUser(await auth.login(email, password));
  }, []);

  const register = useCallback(async (email: string, password: string, name: string) => {
    await auth.register(email, password, name);
    // Intentionally no setUser: the new account still has to sign in.
  }, []);

  const logout = useCallback(() => {
    auth.logout();
    setUser(null);
    router.replace("/login");
  }, [router]);

  const value = useMemo(
    () => ({ user, isAdmin: user?.role === "admin", loading, login, register, logout }),
    [user, loading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (context === null) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
