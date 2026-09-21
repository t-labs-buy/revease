"use client";

/** Admin → Users: every account, with promote/demote and password-reset controls.
 *  The API 403s non-admins; this page also redirects them home. */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { listUsers, setUserRole, type AdminUser } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { fmtDateIST } from "@/lib/time";
import { ResetPasswordDialog } from "@/components/ResetPasswordDialog";

const fmtDate = fmtDateIST;

export default function AdminUsersPage() {
  const { user: me, isAdmin, loading } = useAuth();
  const router = useRouter();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [resetting, setResetting] = useState<AdminUser | null>(null);

  useEffect(() => {
    if (!loading && !isAdmin) router.replace("/");
  }, [loading, isAdmin, router]);

  useEffect(() => {
    if (!isAdmin) return;
    listUsers()
      .then((u) => {
        setUsers(u);
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, [isAdmin]);

  async function changeRole(u: AdminUser, role: "user" | "admin") {
    setBusyId(u.id);
    try {
      const updated = await setUserRole(u.id, role);
      setUsers((us) => us.map((x) => (x.id === u.id ? updated : x)));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  }

  if (loading || !isAdmin) return null;

  return (
    <main className="mx-auto max-w-[1600px] px-8 py-10">
      <h1 className="text-3xl font-semibold tracking-tight text-[var(--text)]">Users</h1>
      <p className="mt-1.5 text-[15px] text-[var(--text-2)]">
        Everyone with an account. Admins can see every user&apos;s projects, manage roles, and
        reset passwords for people who are locked out.
      </p>

      {error && (
        <p className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </p>
      )}

      <div className="card mt-6 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)] text-left text-[var(--text-3)]">
              <th className="px-5 py-3 font-medium">User</th>
              <th className="px-5 py-3 font-medium">Role</th>
              <th className="px-5 py-3 font-medium">Projects</th>
              <th className="px-5 py-3 font-medium">Joined</th>
              <th className="px-5 py-3" />
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const admin = u.role === "admin";
              const self = u.id === me?.id;
              return (
                <tr key={u.id} className="border-b border-[var(--border)] last:border-0">
                  <td className="px-5 py-3">
                    <div className="font-medium text-[var(--text)]">
                      {u.name || u.email.split("@")[0]}
                      {self && <span className="ml-1.5 text-[var(--text-3)]">(you)</span>}
                    </div>
                    <div className="text-[var(--text-3)]">{u.email}</div>
                  </td>
                  <td className="px-5 py-3">
                    <span
                      className={`badge px-2.5 py-0.5 ring-1 ring-inset ${
                        admin
                          ? "bg-[#6d5dfb]/10 text-[var(--brand-2)] ring-[#6d5dfb]/25"
                          : "bg-[var(--hover)] text-[var(--text-2)] ring-[var(--border)]"
                      }`}
                    >
                      {admin ? "Admin" : "User"}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-[var(--text-2)]">{u.project_count}</td>
                  <td className="px-5 py-3 text-[var(--text-2)]">{fmtDate(u.created_at)}</td>
                  <td className="px-5 py-3 text-right whitespace-nowrap">
                    {!self && (
                      <div className="inline-flex gap-2">
                        <button
                          onClick={() => setResetting(u)}
                          disabled={busyId === u.id}
                          className="btn btn-secondary btn-sm disabled:opacity-40"
                        >
                          Reset password
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {resetting && (
        <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />
      )}
    </main>
  );
}
