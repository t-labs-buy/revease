"""Share-to-edit — invite another registered user to edit a project.

The owner (or an admin) invites by email; the invitee must already have a
RevEase account. Collaborators inherit the owner's edit rights on everything
under the project through `owned_project` (see `app.ownership`), and the
project shows up under "Shared with me" in their library. They cannot delete
the project, invite others, or manage its public share links."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db import get_session
from app.models import ProjectCollaborator, User
from app.ownership import owned_project
from app.schemas import CollaboratorCreate, CollaboratorOut

router = APIRouter(prefix="/projects/{project_id}/collaborators", tags=["collaborators"])


def _rows(db: Session, project_id: str) -> list[CollaboratorOut]:
    pairs = db.execute(
        select(ProjectCollaborator, User)
        .join(User, User.id == ProjectCollaborator.user_id)
        .where(ProjectCollaborator.project_id == project_id)
        .order_by(ProjectCollaborator.created_at.asc())
    ).all()
    return [
        CollaboratorOut(user_id=u.id, email=u.email, name=u.name, created_at=c.created_at)
        for c, u in pairs
    ]


@router.get("", response_model=list[CollaboratorOut])
def list_collaborators(
    project_id: str, user: CurrentUser, db: Session = Depends(get_session)
) -> list[CollaboratorOut]:
    """Anyone with access to the project can see who else has it."""
    owned_project(db, user, project_id)
    return _rows(db, project_id)


@router.post("", response_model=list[CollaboratorOut], status_code=status.HTTP_201_CREATED)
def add_collaborator(
    project_id: str,
    payload: CollaboratorCreate,
    user: CurrentUser,
    db: Session = Depends(get_session),
) -> list[CollaboratorOut]:
    """Owner/admin: invite a registered user by email. Idempotent."""
    project = owned_project(db, user, project_id, owner_only=True)
    email = payload.email.strip().lower()
    invitee = db.scalar(select(User).where(User.email == email))
    if invitee is None:
        raise HTTPException(status_code=404, detail="no RevEase account with that email")
    if invitee.id == project.user_id:
        raise HTTPException(status_code=400, detail="that user already owns this project")
    exists = db.scalar(
        select(ProjectCollaborator.id).where(
            ProjectCollaborator.project_id == project_id,
            ProjectCollaborator.user_id == invitee.id,
        )
    )
    if exists is None:
        db.add(ProjectCollaborator(project_id=project_id, user_id=invitee.id, invited_by=user.id))
        db.commit()
    return _rows(db, project_id)


@router.delete("/{user_id}", response_model=list[CollaboratorOut])
def remove_collaborator(
    project_id: str, user_id: str, user: CurrentUser, db: Session = Depends(get_session)
) -> list[CollaboratorOut]:
    """Owner/admin removes anyone; a collaborator may remove themselves (leave)."""
    owned_project(db, user, project_id, owner_only=user_id != user.id)
    row = db.scalar(
        select(ProjectCollaborator).where(
            ProjectCollaborator.project_id == project_id,
            ProjectCollaborator.user_id == user_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="collaborator not found")
    db.delete(row)
    db.commit()
    return _rows(db, project_id)
