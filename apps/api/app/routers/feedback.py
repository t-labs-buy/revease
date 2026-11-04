"""Product feedback: a required star rating plus two optional written answers.

Asked while a video renders or a document generates — the user is waiting anyway.
The web app calls `GET /feedback/status` right after the user starts a generation
(no polling):

- `due`: a video/document generating that this user has never rated. The popup
  cannot be closed until answered. Decided here, not in the browser, so a second
  generation of the same target can't be mistaken for the first.
- `optional`: one generating that they *have* rated before (a regeneration). The
  popup is shown again but has Skip; skipping is remembered in the browser only
  for that generation, so the next regeneration asks again.

Only generations that are queued or running count. A generation that finished before
the user answered is not asked about afterwards (the popup is up the whole time it
runs, so that only happens if the tab was closed). Collaborators are asked too: each
person who can see the project answers for themselves.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import AdminUser, CurrentUser
from app.db import get_session
from app.models import Document, Feedback, Project, RenderJob, VideoProject
from app.ownership import project_ids_for

router = APIRouter(tags=["feedback"])

Kind = Literal["video", "doc"]


class FeedbackDue(BaseModel):
    kind: Kind
    target_id: str
    project_id: str
    project_name: str


class FeedbackStatus(BaseModel):
    due: FeedbackDue | None
    optional: FeedbackDue | None = None


class FeedbackIn(BaseModel):
    kind: Kind
    target_id: str
    rating: int = Field(ge=1, le=5)
    challenges: str | None = Field(default=None, max_length=4000)
    improvements: str | None = Field(default=None, max_length=4000)

    @field_validator("challenges", "improvements")
    @classmethod
    def _blank_is_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


class FeedbackOut(BaseModel):
    id: str
    email: str
    kind: str
    target_id: str
    project_id: str | None
    project_name: str | None = None
    rating: int
    challenges: str | None
    improvements: str | None
    created_at: datetime


def _answered(db: Session, user_id: str) -> set[tuple[str, str]]:
    rows = db.execute(select(Feedback.kind, Feedback.target_id).where(Feedback.user_id == user_id))
    return {(k, t) for k, t in rows}


def _running(db: Session, pids: list[str]) -> list[tuple[str, str, str]]:
    """(kind, target_id, project_id) for every generation in flight, oldest first."""
    videos = db.execute(
        select(VideoProject.id, VideoProject.project_id, RenderJob.created_at)
        .join(RenderJob, RenderJob.video_project_id == VideoProject.id)
        .where(VideoProject.project_id.in_(pids), RenderJob.status.in_(("pending", "running")))
    ).all()
    docs = db.execute(
        select(Document.id, Document.project_id, Document.updated_at).where(
            Document.project_id.in_(pids), Document.status.in_(("queued", "running"))
        )
    ).all()
    found = [("video", vid, pid, at) for vid, pid, at in videos] + [
        ("doc", did, pid, at) for did, pid, at in docs
    ]
    found.sort(key=lambda r: r[3])
    return [(k, t, p) for k, t, p, _ in found]


@router.get("/feedback/status", response_model=FeedbackStatus)
def feedback_status(user: CurrentUser, db: Session = Depends(get_session)) -> FeedbackStatus:
    pids = project_ids_for(db, user)
    if not pids:
        return FeedbackStatus(due=None)
    answered = _answered(db, user.id)
    due: FeedbackDue | None = None
    optional: FeedbackDue | None = None
    for kind, target, pid in _running(db, pids):
        slot = "optional" if (kind, target) in answered else "due"
        if (due if slot == "due" else optional) is not None:
            continue
        name = db.scalar(select(Project.name).where(Project.id == pid)) or ""
        item = FeedbackDue(kind=kind, target_id=target, project_id=pid, project_name=name)
        if slot == "due":
            due = item
        else:
            optional = item
    return FeedbackStatus(due=due, optional=optional)


def _project_of(db: Session, kind: str, target_id: str) -> str | None:
    model = VideoProject if kind == "video" else Document
    return db.scalar(select(model.project_id).where(model.id == target_id))


@router.post("/feedback", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
def submit_feedback(
    payload: FeedbackIn, user: CurrentUser, db: Session = Depends(get_session)
) -> FeedbackOut:
    pid = _project_of(db, payload.kind, payload.target_id)
    # a video/document you can't see is a 404, never a 403 (see ownership.py)
    if pid is None or pid not in project_ids_for(db, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    # a repeat answer is only taken while that video/document is regenerating
    key = (payload.kind, payload.target_id)
    running = {(k, t) for k, t, _ in _running(db, [pid])}
    if key in _answered(db, user.id) and key not in running:
        raise HTTPException(status.HTTP_409_CONFLICT, "feedback already submitted")
    row = Feedback(
        user_id=user.id,
        email=user.email,
        kind=payload.kind,
        target_id=payload.target_id,
        project_id=pid,
        rating=payload.rating,
        challenges=payload.challenges,
        improvements=payload.improvements,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return FeedbackOut.model_validate(row, from_attributes=True)


class FeedbackList(BaseModel):
    count: int
    average: float | None
    items: list[FeedbackOut]


@router.get("/admin/feedback", response_model=FeedbackList)
def list_feedback(admin: AdminUser, db: Session = Depends(get_session)) -> FeedbackList:
    rows = db.execute(
        select(Feedback, Project.name)
        .outerjoin(Project, Project.id == Feedback.project_id)
        .order_by(Feedback.created_at.desc())
    ).all()
    avg = db.scalar(select(func.avg(Feedback.rating)))
    items = [
        FeedbackOut.model_validate(f, from_attributes=True).model_copy(update={"project_name": name})
        for f, name in rows
    ]
    return FeedbackList(
        count=len(items), average=round(float(avg), 2) if avg is not None else None, items=items
    )
