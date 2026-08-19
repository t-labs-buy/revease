"""Smart auto-edit API: speed up silent parts + zoom on motion, from the raw video."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db import get_session
from app.models import AutoEditJob, CaptureSession, MediaAsset
from app.ownership import owned_autoedit_job, owned_project
from app.queue import enqueue_autoedit
from app.schemas import AutoEditOut, AutoEditStart
from app.storage import store

router = APIRouter(tags=["autoedit"])


def _out(job: AutoEditJob) -> AutoEditOut:
    return AutoEditOut(
        id=job.id,
        status=job.status,
        output_key=job.output_key,
        output_url=store.download_url(job.output_key) if job.output_key else None,
        stats_json=job.stats_json,
        error_json=job.error_json,
    )


@router.post("/projects/{project_id}/autoedit", response_model=AutoEditOut)
def start_autoedit(
    project_id: str,
    user: CurrentUser,
    payload: AutoEditStart | None = None,
    db: Session = Depends(get_session),
) -> AutoEditOut:
    owned_project(db, user, project_id)
    # require a raw video somewhere in the project
    has_video = db.scalar(
        select(MediaAsset.id)
        .join(CaptureSession, CaptureSession.id == MediaAsset.session_id)
        .where(CaptureSession.project_id == project_id, MediaAsset.kind == "raw_video")
    )
    if not has_video:
        raise HTTPException(status_code=404, detail="no source video in this project")
    opts = (payload or AutoEditStart()).model_dump()
    job = AutoEditJob(project_id=project_id, status="pending", options_json=opts)
    db.add(job)
    db.commit()
    db.refresh(job)
    enqueue_autoedit(job.id)
    return _out(job)


@router.get("/autoedit/{job_id}", response_model=AutoEditOut)
def get_autoedit(
    job_id: str, user: CurrentUser, db: Session = Depends(get_session)
) -> AutoEditOut:
    return _out(owned_autoedit_job(db, user, job_id))
