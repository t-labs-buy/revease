"""Admin — user management. Every route requires the admin role (403 otherwise).

The first admin comes from REFRACT_ADMIN_EMAILS (promoted at register/login);
from there admins can promote or demote anyone here. You cannot change your own
role, so an admin can never lock themselves out mid-session.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import AdminUser
from app.config import get_settings
from app.db import get_session
from app.models import Project, User
from app.schemas import UserOut

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminUserOut(UserOut):
    project_count: int = 0


class RoleUpdate(BaseModel):
    role: Literal["user", "admin"]


@router.get("/users", response_model=list[AdminUserOut])
def list_users(admin: AdminUser, db: Session = Depends(get_session)) -> list[AdminUserOut]:
    counts = dict(
        db.execute(
            select(Project.user_id, func.count()).where(Project.user_id.is_not(None)).group_by(Project.user_id)
        ).all()
    )
    users = db.scalars(select(User).order_by(User.created_at.asc()))
    return [
        AdminUserOut(**UserOut.model_validate(u).model_dump(), project_count=counts.get(u.id, 0))
        for u in users
    ]


@router.patch("/users/{user_id}/role", response_model=AdminUserOut)
def set_role(
    user_id: str, payload: RoleUpdate, admin: AdminUser, db: Session = Depends(get_session)
) -> AdminUserOut:
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="you cannot change your own role")
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    if payload.role == "user" and target.email in get_settings().admin_email_set():
        # Pointless demotion: the env listing re-promotes them at next login.
        raise HTTPException(
            status_code=400,
            detail="this user is a bootstrap admin (REFRACT_ADMIN_EMAILS) — remove them there first",
        )
    target.role = payload.role
    db.commit()
    db.refresh(target)
    count = (
        db.scalar(select(func.count()).select_from(Project).where(Project.user_id == target.id)) or 0
    )
    return AdminUserOut(**UserOut.model_validate(target).model_dump(), project_count=count)
