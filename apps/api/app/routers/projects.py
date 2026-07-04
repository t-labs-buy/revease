"""Project CRUD — the top-level V1 entity (no auth, single-user)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Project
from app.schemas import ProjectCreate, ProjectOut

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
