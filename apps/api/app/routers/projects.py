"""Project CRUD — the top-level entity in a user's private space."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db import get_session
from app.models import CaptureSession, Document, Project
from app.ownership import delete_project_cascade, owned_project, purge_media
from app.schemas import ProjectCreate, ProjectOut

router = APIRouter(prefix="/projects", tags=["projects"])


def _out(db: Session, project: Project) -> ProjectOut:
    """Project plus the two facts the UI needs but can't infer: whether a doc has
    really been generated, and how many captures the project holds."""
    out = ProjectOut.model_validate(project)
    out.has_document = (
        db.scalar(select(Document.id).where(Document.project_id == project.id)) is not None
    )
    out.capture_count = (
        db.scalar(
            select(func.count())
            .select_from(CaptureSession)
            .where(CaptureSession.project_id == project.id)
        )
        or 0
    )
    return out


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate, user: CurrentUser, db: Session = Depends(get_session)
) -> ProjectOut:
    project = Project(name=payload.name, user_id=user.id)
    db.add(project)
    db.commit()
    db.refresh(project)
    return _out(db, project)


@router.get("", response_model=list[ProjectOut])
def list_projects(user: CurrentUser, db: Session = Depends(get_session)) -> list[ProjectOut]:
    projects = db.scalars(
        select(Project)
        .where(Project.user_id == user.id)
        .order_by(Project.favorite.desc(), Project.created_at.desc())
    )
    return [_out(db, p) for p in projects]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: str, user: CurrentUser, db: Session = Depends(get_session)
) -> ProjectOut:
    return _out(db, owned_project(db, user, project_id))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: str, user: CurrentUser, db: Session = Depends(get_session)
) -> None:
    """Remove a project and everything under it: sessions (events/assets/jobs/
    transcripts), workflow graphs, video project + render jobs, documents, shares,
    auto-edit / auto-record runs — plus best-effort cleanup of media on disk."""
    project = owned_project(db, user, project_id)
    sess_ids, vp_ids = delete_project_cascade(db, project)
    db.commit()
    purge_media(sess_ids, vp_ids)  # the DB delete already succeeded


@router.post("/{project_id}/favorite", response_model=ProjectOut)
def toggle_favorite(
    project_id: str, user: CurrentUser, db: Session = Depends(get_session)
) -> ProjectOut:
    """Star/unstar a project — starred projects sort first."""
    project = owned_project(db, user, project_id)
    project.favorite = 0 if project.favorite else 1
    db.commit()
    db.refresh(project)
    return _out(db, project)
