/**
 * The transport every API call goes through.
 *
 * `apiFetch` prepends the API base, attaches the stored bearer token, and — on a
 * 401 — clears the token and notifies whoever registered `onUnauthorized` (the
 * AuthProvider, which bounces the user to /login). It deliberately does NOT throw
 * on non-2xx: callers already branch on `r.ok` / `r.status === 404`, and keeping
 * that contract means adding auth didn't change how any endpoint reports errors.
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const TOKEN_KEY = "revease.access_token";

// In-memory mirror of the token so the very first request after login doesn't
// have to wait on a storage read, and so SSR (no localStorage) is harmless.
let cachedToken: string | null = null;

export function getToken(): string | null {
  if (cachedToken !== null) return cachedToken;
  if (typeof window === "undefined") return null;
  try {
    cachedToken = window.localStorage.getItem(TOKEN_KEY);
  } catch {
    cachedToken = null; // private mode / storage disabled
  }
  return cachedToken;
}

export function setToken(token: string): void {
  cachedToken = token;
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* keep the in-memory token; this session still works */
  }
}

export function clearToken(): void {
  cachedToken = null;
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export function authHeader(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

/** Register the app-wide reaction to an expired/invalid token. */
export function onUnauthorized(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

/** Endpoints that are public by design — a 401 from these is a real error to
 *  surface in the form, not a signal that the session expired. */
const PUBLIC_PATHS = ["/auth/login", "/auth/register"];

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });

  if (response.status === 401 && !PUBLIC_PATHS.some((p) => path.startsWith(p))) {
    clearToken();
    unauthorizedHandler?.();
  }
  return response;
}

/** Pull FastAPI's `detail` out of an error response, falling back to `fallback`. */
export async function errorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    // 422 from Pydantic: [{ loc, msg, ... }]
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  } catch {
    /* not JSON */
  }
  return fallback;
}
