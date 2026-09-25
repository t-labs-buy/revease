"""What is processing right now, across the caller's projects — the header's
activity indicator polls this so work stays visible after the user navigates
away from the page that started it.

One cheap query per kind (pipeline sessions, documents, renders), each limited
to rows that are in flight or finished in the last few minutes (so a "done"
tick can show before the item disappears).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.config import get_settings
from app.db import get_session
from app.models import CaptureSession, Document, Job, Project, RenderJob, VideoProject
from app.ownership import project_ids_for
from app.progress import summarize
from app.schemas import ActivityItem

router = APIRouter(tags=["activity"])

RECENT = timedelta(minutes=3)


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.get("/activity", response_model=list[ActivityItem])
def list_activity(user: CurrentUser, db: Session = Depends(get_session)) -> list[ActivityItem]:
    pids = project_ids_for(db, user)
    if not pids:
        return []
    names = dict(db.execute(select(Project.id, Project.name).where(Project.id.in_(pids))).all())
    now = datetime.now(timezone.utc)
    stale = get_settings().pipeline_stale_after_s
    out: list[ActivityItem] = []

    # recordings being understood
    for sess in db.scalars(
        select(CaptureSession).where(
            CaptureSession.project_id.in_(pids), CaptureSession.status.in_(("captured", "processing"))
        )
    ):
        version = db.scalar(select(func.max(Job.version)).where(Job.session_id == sess.id))
        jobs = list(db.scalars(select(Job).where(Job.session_id == sess.id, Job.version == version))) if version else []
        s = summarize(jobs, now=now, stale_after_s=stale)
        out.append(ActivityItem(
            kind="processing", project_id=sess.project_id, project_name=names.get(sess.project_id, "Project"),
            status="stalled" if s.stalled else ("queued" if not jobs else "running"),
            progress=s.progress if jobs else 0.0,
            message=s.message or ("Waiting for a worker…" if not jobs
                                  else "Finishing up…" if s.progress >= 1 else None),
            href=f"/projects/{sess.project_id}/prepare?sid={sess.id}",
            started_at=min((_utc(j.started_at) for j in jobs if j.started_at), default=None),
            updated_at=max((_utc(j.updated_at) for j in jobs if j.updated_at), default=None),
        ))

    # documents
    for doc in db.scalars(
        select(Document).where(
            Document.project_id.in_(pids),
            or_(Document.status.in_(("queued", "running")),
                Document.updated_at >= (now - RECENT)),
        )
    ):
        if doc.status not in ("queued", "running", "error") and (doc.progress or 0) < 1:
            continue  # an old ready doc merely edited recently
        out.append(ActivityItem(
            kind="document", project_id=doc.project_id, project_name=names.get(doc.project_id, "Project"),
            status=doc.status, progress=doc.progress, message=doc.message,
            href=f"/projects/{doc.project_id}/document", updated_at=_utc(doc.updated_at),
        ))

    # renders
    for job, project_id in db.execute(
        select(RenderJob, VideoProject.project_id)
        .join(VideoProject, VideoProject.id == RenderJob.video_project_id)
        .where(
            VideoProject.project_id.in_(pids),
            or_(RenderJob.status.in_(("pending", "running")),
                RenderJob.updated_at >= (now - RECENT)),
        )
    ).all():
        out.append(ActivityItem(
            kind="render", project_id=project_id, project_name=names.get(project_id, "Project"),
            status="queued" if job.status == "pending" else job.status, progress=job.progress,
            message=job.message, href=f"/projects/{project_id}/video", started_at=_utc(job.created_at),
            updated_at=_utc(job.updated_at),
        ))

    order = {"running": 0, "stalled": 1, "queued": 2, "error": 3}
    out.sort(key=lambda a: (order.get(a.status, 4), -(a.updated_at.timestamp() if a.updated_at else 0)))
    return out[:20]
