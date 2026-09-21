"use client";

/** The two sharing controls in an editor header:
 *
 *  - "Collaborators": share-to-edit. The owner (or an admin) invites registered
 *    users by email and can remove them; an invited user sees who else has
 *    access and can leave.
 *  - "Share": the public link (see ShareButton). Owner/admin only — the API
 *    404s it for collaborators, so it is simply not shown to them. */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  addCollaborator,
  getProject,
  listCollaborators,
  removeCollaborator,
  type Collaborator,
  type Project,
} from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { ShareButton } from "@/components/ShareButton";

export function ProjectAccess({ projectId, kind }: { projectId: string; kind: "video" | "doc" }) {
  const { user, isAdmin } = useAuth();
  const router = useRouter();
  const [project, setProject] = useState<Project | null>(null);
  const [open, setOpen] = useState(false);
  const [people, setPeople] = useState<Collaborator[] | null>(null);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getProject(projectId).then(setProject).catch(() => setProject(null));
  }, [projectId]);

  // Owner and admins manage the list; an invitee can only view it and leave.
  const canManage = !!project && (!project.shared_with_me || isAdmin);

  async function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    setError(null);
    try {
      setPeople(await listCollaborators(projectId));
    } catch (e) {
      setError(String(e));
    }
  }

  async function invite() {
    const target = email.trim();
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      setPeople(await addCollaborator(projectId, target));
      setEmail("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove(userId: string) {
    setBusy(true);
    setError(null);
    try {
      const next = await removeCollaborator(projectId, userId);
      if (userId === user?.id && !isAdmin) {
        router.replace("/library"); // we just left — the project is no longer ours to see
        return;
      }
      setPeople(next);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="relative">
        <button
          onClick={toggle}
          className="btn btn-secondary btn-sm"
          title={canManage ? "Invite another RevEase user to edit this project" : "Who can edit this project"}
        >
          👥 {canManage ? "Collaborators" : "Shared with you"}
        </button>
        {open && (
          <div className="absolute right-0 z-40 mt-2 w-96 rounded-xl border border-[var(--border)] bg-[var(--card)] p-3 shadow-2xl">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-medium">
                {canManage ? "Share to edit" : "People with edit access"}
              </span>
              <button onClick={() => setOpen(false)} className="btn btn-ghost btn-sm">
                ✕
              </button>
            </div>

            {project?.shared_with_me && project.owner_email && (
              <p className="mb-2 text-xs text-[var(--text-2)]">
                Owner: {project.owner_name || project.owner_email}
              </p>
            )}

            {canManage && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void invite();
                }}
                className="flex gap-2"
              >
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="Email of a RevEase user"
                  className="input flex-1 text-sm"
                  required
                />
                <button type="submit" disabled={busy || !email.trim()} className="btn btn-primary btn-sm">
                  {busy ? "…" : "Invite"}
                </button>
              </form>
            )}

            {error && <p className="mt-2 text-xs text-red-500">{error}</p>}

            <ul className="mt-3 max-h-56 space-y-1.5 overflow-y-auto">
              {people === null && !error && (
                <li className="text-xs text-[var(--text-3)]">Loading…</li>
              )}
              {people?.length === 0 && (
                <li className="text-xs text-[var(--text-3)]">
                  {canManage
                    ? "No one else can edit this project yet."
                    : "You are the only person invited."}
                </li>
              )}
              {people?.map((c) => {
                const isMe = c.user_id === user?.id;
                return (
                  <li key={c.user_id} className="flex items-center gap-2 text-sm">
                    <div className="min-w-0 flex-1">
                      <div className="truncate">
                        {c.name || c.email}
                        {isMe && <span className="text-[var(--text-3)]"> (you)</span>}
                      </div>
                      {c.name && <div className="truncate text-xs text-[var(--text-3)]">{c.email}</div>}
                    </div>
                    {(canManage || isMe) && (
                      <button
                        onClick={() => void remove(c.user_id)}
                        disabled={busy}
                        className="btn btn-ghost btn-sm text-red-400"
                      >
                        {isMe && !canManage ? "Leave" : "Remove"}
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>

            {canManage && (
              <p className="mt-3 text-xs text-[var(--text-2)]">
                Invited people can edit everything in this project. Only you can remove the
                project, invite others, or manage public links.
              </p>
            )}
          </div>
        )}
      </div>
      {canManage && <ShareButton projectId={projectId} kind={kind} />}
    </>
  );
}
