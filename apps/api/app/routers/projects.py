"""Project CRUD — the top-level V1 entity (no auth, single-user)."""

from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import (
    AutoEditJob,
    AutoRecordRun,
    CaptureSession,
    Document,
    Job,
    Project,
    RenderJob,
    Share,
    Transcript,
    VideoProject,
)
from app.schemas import ProjectCreate, ProjectOut
from app.storage import store

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_session)) -> Project:
    project = Project(name=payload.name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_session)) -> list[Project]:
    return list(
        db.scalars(select(Project).order_by(Project.favorite.desc(), Project.created_at.desc()))
    )


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_session)) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, db: Session = Depends(get_session)) -> None:
    """Remove a project and everything under it: sessions (events/assets/jobs/
    transcripts), workflow graphs, video project + render jobs, documents, shares,
    auto-edit / auto-record runs — plus best-effort cleanup of media on disk."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    sess_ids = [
        s.id for s in db.scalars(select(CaptureSession).where(CaptureSession.project_id == project_id))
    ]
    vp_ids = [
        v.id for v in db.scalars(select(VideoProject).where(VideoProject.project_id == project_id))
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
    db.commit()

    # best-effort media cleanup — the DB delete already succeeded
    for key in [*(f"sessions/{sid}" for sid in sess_ids), *(f"renders/{vid}" for vid in vp_ids)]:
        try:
            p = store.local_path(key)
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        except ValueError:
            pass


@router.post("/{project_id}/favorite", response_model=ProjectOut)
def toggle_favorite(project_id: str, db: Session = Depends(get_session)) -> Project:
    """Star/unstar a project — starred projects sort first."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    project.favorite = 0 if project.favorite else 1
    db.commit()
    db.refresh(project)
    return project
