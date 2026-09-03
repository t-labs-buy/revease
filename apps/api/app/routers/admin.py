"""Admin — user management. Every route requires the admin role (403 otherwise).

The first admin comes from REFRACT_ADMIN_EMAILS (promoted at register/login);
from there admins can promote or demote anyone here. You cannot change your own
role, so an admin can never lock themselves out mid-session.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import AdminUser
from app.config import get_settings
from app.db import get_session
from app.models import Project, UsageEvent, User
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


# --------------------------------------------------------------------------- #
# usage
# --------------------------------------------------------------------------- #
# Usage timestamps are stored and served as naive IST (UTC+05:30) wall-clock
# time, and from/to date filters mean IST calendar days.
def _ist_start(day: date) -> datetime:
    return datetime.combine(day, time.min)


class UsageSummaryOut(BaseModel):
    videos_generated: int
    screens_recorded: int
    videos_uploaded: int
    video_duration_ms: int  # combined length of the generated videos in range
    recording_duration_ms: int  # combined length of the screen recordings in range
    upload_duration_ms: int  # combined length of the uploaded videos in range
    from_date: date | None = None
    to_date: date | None = None


def _usage_summary(db: Session, from_: date | None, to: date | None) -> UsageSummaryOut:
    q = select(
        UsageEvent.kind, func.count(), func.coalesce(func.sum(UsageEvent.duration_ms), 0)
    ).group_by(UsageEvent.kind)
    if from_ is not None:
        q = q.where(UsageEvent.created_at >= _ist_start(from_))
    if to is not None:
        # inclusive end date: everything before the next IST midnight
        q = q.where(UsageEvent.created_at < _ist_start(to + timedelta(days=1)))
    rows = {kind: (count, duration) for kind, count, duration in db.execute(q).all()}
    return UsageSummaryOut(
        videos_generated=rows.get("video", (0, 0))[0],
        screens_recorded=rows.get("recording", (0, 0))[0],
        videos_uploaded=rows.get("upload", (0, 0))[0],
        video_duration_ms=rows.get("video", (0, 0))[1],
        recording_duration_ms=rows.get("recording", (0, 0))[1],
        upload_duration_ms=rows.get("upload", (0, 0))[1],
        from_date=from_,
        to_date=to,
    )


@router.get("/usage", response_model=UsageSummaryOut)
def usage_summary(
    admin: AdminUser,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    db: Session = Depends(get_session),
) -> UsageSummaryOut:
    """Totals of videos generated and screens recorded, optionally limited to an
    inclusive date range (dates are IST calendar days). Admin only."""
    return _usage_summary(db, from_, to)


class UsageEventOut(BaseModel):
    kind: str  # "video" | "recording" | "upload"
    user_email: str | None = None
    user_name: str | None = None
    duration_ms: int | None = None
    created_at: datetime


def _apply_range(q, from_: date | None, to: date | None):
    if from_ is not None:
        q = q.where(UsageEvent.created_at >= _ist_start(from_))
    if to is not None:
        q = q.where(UsageEvent.created_at < _ist_start(to + timedelta(days=1)))
    return q


def _usage_events(
    db: Session, from_: date | None, to: date | None, limit: int, offset: int = 0
) -> list[UsageEventOut]:
    q = _apply_range(
        select(UsageEvent, User).join(User, User.id == UsageEvent.user_id, isouter=True),
        from_,
        to,
    ).order_by(UsageEvent.created_at.desc()).limit(limit).offset(offset)
    return [
        UsageEventOut(
            kind=event.kind,
            user_email=owner.email if owner else None,
            user_name=owner.name if owner else None,
            duration_ms=event.duration_ms,
            created_at=event.created_at,
        )
        for event, owner in db.execute(q).all()
    ]


class UsageEventsPageOut(BaseModel):
    total: int  # events matching the range, across all pages
    events: list[UsageEventOut]


@router.get("/usage/events", response_model=UsageEventsPageOut)
def usage_events(
    admin: AdminUser,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    limit: int = Query(default=25, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
) -> UsageEventsPageOut:
    """One page of the per-event detail behind the summary: who did what, when
    (IST). Newest first. Events from before user attribution existed have no user."""
    total = db.scalar(
        _apply_range(select(func.count()).select_from(UsageEvent), from_, to)
    ) or 0
    return UsageEventsPageOut(total=total, events=_usage_events(db, from_, to, limit, offset))


class UsageReportOut(UsageSummaryOut):
    events_total: int  # events matching the range, across all pages
    events: list[UsageEventOut]


@router.get("/usage/report", response_model=UsageReportOut)
def usage_report(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    limit: int = Query(default=1000, le=10000),
    offset: int = Query(default=0, ge=0),
    x_report_key: str = Header(default=""),
    db: Session = Depends(get_session),
) -> UsageReportOut:
    """Totals plus one page of per-event detail for an external app,
    authenticated by the static X-Report-Key header (REFRACT_USAGE_REPORT_KEY)
    instead of a login. Disabled while no key is configured. Page with
    limit/offset until `events_total` is reached; the summary totals always
    cover the whole range regardless of paging."""
    key = get_settings().usage_report_key
    if not key:
        raise HTTPException(status_code=404, detail="usage reporting is not enabled")
    if not secrets.compare_digest(x_report_key, key):
        raise HTTPException(status_code=401, detail="invalid report key")
    summary = _usage_summary(db, from_, to)
    events_total = db.scalar(
        _apply_range(select(func.count()).select_from(UsageEvent), from_, to)
    ) or 0
    return UsageReportOut(
        **summary.model_dump(),
        events_total=events_total,
        events=_usage_events(db, from_, to, limit, offset),
    )
