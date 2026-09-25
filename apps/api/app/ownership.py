"""Ownership resolution — the one place routes turn an id into a row the caller
is allowed to touch.

Two rules hold everywhere:

* A row the caller does not own is reported as **404, not 403**. A 403 would
  confirm the id exists in someone else's space; 404 leaks nothing.
* Only the four top-level entities carry `user_id`. Everything else is reached
  through its Project, so `owned_*` walks up to the project and checks that.
* A project's collaborators (see `ProjectCollaborator`) pass the project check
  like the owner does, so every edit route accepts them without changes. The
  few owner-only actions (delete, invite, public share links) pass
  `owner_only=True`. Admins pass everything.
"""

from __future__ import annotations

from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.orm import Session

from app.models import (
    Upload,
    AutoEditJob,
    AutoRecordRun,
    BrandPackage,
    CaptureSession,
    Document,
    Job,
    KbArticle,
    Project,
    ProjectCollaborator,
    RenderJob,
    Share,
    Skill,
    Transcript,
    User,
    VideoProject,
)
from app.storage import store

# The top-level entities that carry an owner column directly.
OWNED_MODELS = (Project, Skill, KbArticle, BrandPackage)

_T = TypeVar("_T", Skill, KbArticle, BrandPackage)


def _missing(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


def is_collaborator(db: Session, user: User, project_id: str) -> bool:
    return (
        db.scalar(
            select(ProjectCollaborator.id).where(
                ProjectCollaborator.project_id == project_id,
                ProjectCollaborator.user_id == user.id,
            )
        )
        is not None
    )


def owned_project(
    db: Session, user: User, project_id: str, *, owner_only: bool = False
) -> Project:
    """The project if the caller may touch it: its owner, an admin, or (unless
    `owner_only`) a collaborator invited by the owner. Otherwise 404."""
    project = db.get(Project, project_id)
    if project is None:
        raise _missing("project")
    if project.user_id == user.id or user.is_admin:
        return project
    if not owner_only and is_collaborator(db, user, project_id):
        return project
    raise _missing("project")


def owned_row(db: Session, user: User, model: type[_T], row_id: str, what: str) -> _T:
    """Fetch a directly-owned row (Skill / KbArticle / BrandPackage)."""
    row = db.get(model, row_id)
    if row is None or (row.user_id != user.id and not user.is_admin):
        raise _missing(what)
    return row


def owned_session(db: Session, user: User, session_id: str) -> CaptureSession:
    sess = db.get(CaptureSession, session_id)
    if sess is None:
        raise _missing("session")
    owned_project(db, user, sess.project_id)  # 404s if the project isn't the caller's
    return sess


def owned_autorecord_run(db: Session, user: User, run_id: str) -> AutoRecordRun:
    run = db.get(AutoRecordRun, run_id)
    if run is None:
        raise _missing("run")
    owned_project(db, user, run.project_id)
    return run


def owned_autoedit_job(db: Session, user: User, job_id: str) -> AutoEditJob:
    job = db.get(AutoEditJob, job_id)
    if job is None:
        raise _missing("job")
    owned_project(db, user, job.project_id)
    return job


def owned_render_job(db: Session, user: User, job_id: str) -> RenderJob:
    job = db.get(RenderJob, job_id)
    if job is None:
        raise _missing("render job")
    vp = db.get(VideoProject, job.video_project_id)
    if vp is None:
        raise _missing("render job")
    owned_project(db, user, vp.project_id)
    return job


def project_ids_for(db: Session, user: User, *, all_spaces: bool = False) -> list[str]:
    """Every project id in this user's space — for scoping list queries.

    `all_spaces=True` widens to every user's projects, but only for admins;
    for regular users it is silently ignored, so callers can pass the client's
    requested scope straight through."""
    if all_spaces and user.is_admin:
        return list(db.scalars(select(Project.id)))
    own = list(db.scalars(select(Project.id).where(Project.user_id == user.id)))
    shared = list(
        db.scalars(
            select(ProjectCollaborator.project_id).where(ProjectCollaborator.user_id == user.id)
        )
    )
    return list(dict.fromkeys([*own, *shared]))  # de-duplicated, own first


# --------------------------------------------------------------------------- #
# cascade delete
# --------------------------------------------------------------------------- #
def delete_project_cascade(db: Session, project: Project) -> tuple[list[str], list[str]]:
    """Queue deletion of a project and everything under it: sessions (events/assets/
    jobs/transcripts), workflow graphs, video project + render jobs, documents,
    shares, auto-edit / auto-record runs.

    Does not commit, and does NOT touch media on disk — it returns the
    `(session_ids, video_project_ids)` whose media directories the caller should
    hand to `purge_media()` *after* the commit succeeds, so a failed transaction
    can never leave the DB pointing at files that are already gone."""
    project_id = project.id
    sess_ids = [
        s.id
        for s in db.scalars(
            select(CaptureSession).where(CaptureSession.project_id == project_id)
        )
    ]
    vp_ids = [
        v.id
        for v in db.scalars(select(VideoProject).where(VideoProject.project_id == project_id))
    ]

    # children keyed by session / video-project (no ORM relationship to cascade)
    if sess_ids:
        db.execute(sa_delete(Upload).where(Upload.session_id.in_(sess_ids)))
        db.execute(sa_delete(Job).where(Job.session_id.in_(sess_ids)))
        db.execute(sa_delete(Transcript).where(Transcript.session_id.in_(sess_ids)))
    if vp_ids:
        db.execute(sa_delete(RenderJob).where(RenderJob.video_project_id.in_(vp_ids)))
    db.execute(sa_delete(VideoProject).where(VideoProject.project_id == project_id))
    db.execute(sa_delete(Document).where(Document.project_id == project_id))
    db.execute(sa_delete(Share).where(Share.project_id == project_id))
    db.execute(sa_delete(ProjectCollaborator).where(ProjectCollaborator.project_id == project_id))
    db.execute(sa_delete(AutoEditJob).where(AutoEditJob.project_id == project_id))
    db.execute(sa_delete(AutoRecordRun).where(AutoRecordRun.project_id == project_id))

    # sessions + graphs (and their events/assets) cascade from the project row
    db.delete(project)
    return sess_ids, vp_ids


def purge_media(sess_ids: list[str], vp_ids: list[str]) -> None:
    """Best-effort media cleanup — never fail a delete over leftover files."""
    for key in [*(f"sessions/{sid}/" for sid in sess_ids), *(f"renders/{vid}/" for vid in vp_ids)]:
        try:
            store.delete_prefix(key)
        except Exception as e:  # noqa: BLE001 - a leftover file must not fail a delete
            import logging

            logging.getLogger("refract.ownership").warning("purge %s failed: %s", key, e)
