/** Account API: register, log in, and identify the current user.
 *
 * Logging out is purely client-side — the token is stateless, so dropping it is
 * the whole operation. There is no "forgot password" email flow (the backend
 * has no email transport); a locked-out user asks an admin, who sets a new
 * password from Admin → Users (see `resetUserPassword` in lib/api.ts).
 */

import { apiFetch, clearToken, errorDetail, getToken, setToken } from "@/lib/http";

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role?: "user" | "admin" | null; // absent/null means "user"
  created_at: string;
}

interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
}

async function post(
  path: string,
  body: Record<string, string>,
  fallback: string,
): Promise<Response> {
  let response: Response;
  try {
    response = await apiFetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    // fetch only rejects when the request never completed — server down, wrong
    // API base, blocked by CORS. "Failed to fetch" means nothing to a user.
    throw new Error("Can't reach the server. Check that the API is running.");
  }
  if (!response.ok) throw new Error(await errorDetail(response, fallback));
  return response;
}

/** Sign in and store the token. This is the only call that starts a session. */
export async function login(email: string, password: string): Promise<AuthUser> {
  const response = await post(
    "/auth/login",
    { email, password },
    "Invalid email or password",
  );
  const data: TokenResponse = await response.json();
  setToken(data.access_token);
  return data.user;
}

/** Create an account. Does NOT sign in — the caller sends the user to /login. */
export async function register(
  email: string,
  password: string,
  name: string,
): Promise<AuthUser> {
  const response = await post(
    "/auth/register",
    { email, password, name },
    "Could not create your account",
  );
  return response.json();
}

/** Resolve the stored token to its account, or null if there isn't a valid one. */
export async function fetchMe(): Promise<AuthUser | null> {
  if (!getToken()) return null;
  const response = await apiFetch("/auth/me", { cache: "no-store" });
  if (!response.ok) return null; // apiFetch already cleared an invalid token
  return response.json();
}

export function logout(): void {
  clearToken();
}

export { getToken };
