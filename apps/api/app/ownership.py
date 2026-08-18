"""Ownership resolution — the one place routes turn an id into a row the caller
is allowed to touch.

Two rules hold everywhere:

* A row the caller does not own is reported as **404, not 403**. A 403 would
  confirm the id exists in someone else's space; 404 leaks nothing.
* Only the four top-level entities carry `user_id`. Everything else is reached
  through its Project, so `owned_*` walks up to the project and checks that.
"""

from __future__ import annotations

import shutil
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.orm import Session

from app.models import (
    AutoEditJob,
    AutoRecordRun,
    BrandPackage,
    CaptureSession,
    Document,
    Job,
    KbArticle,
    Project,
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


def owned_project(db: Session, user: User, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise _missing("project")
    return project


def owned_row(db: Session, user: User, model: type[_T], row_id: str, what: str) -> _T:
    """Fetch a directly-owned row (Skill / KbArticle / BrandPackage)."""
    row = db.get(model, row_id)
    if row is None or row.user_id != user.id:
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


def project_ids_for(db: Session, user: User) -> list[str]:
    """Every project id in this user's space — for scoping list queries."""
    return list(db.scalars(select(Project.id).where(Project.user_id == user.id)))


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
        db.execute(sa_delete(Job).where(Job.session_id.in_(sess_ids)))
        db.execute(sa_delete(Transcript).where(Transcript.session_id.in_(sess_ids)))
    if vp_ids:
        db.execute(sa_delete(RenderJob).where(RenderJob.video_project_id.in_(vp_ids)))
    db.execute(sa_delete(VideoProject).where(VideoProject.project_id == project_id))
    db.execute(sa_delete(Document).where(Document.project_id == project_id))
    db.execute(sa_delete(Share).where(Share.project_id == project_id))
    db.execute(sa_delete(AutoEditJob).where(AutoEditJob.project_id == project_id))
    db.execute(sa_delete(AutoRecordRun).where(AutoRecordRun.project_id == project_id))

    # sessions + graphs (and their events/assets) cascade from the project row
    db.delete(project)
    return sess_ids, vp_ids


def purge_media(sess_ids: list[str], vp_ids: list[str]) -> None:
    """Best-effort media cleanup — never fail a delete over leftover files."""
    for key in [*(f"sessions/{sid}" for sid in sess_ids), *(f"renders/{vid}" for vid in vp_ids)]:
        try:
            path = store.local_path(key)
        except ValueError:
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
