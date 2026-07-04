"""Capture sessions — the primitive every downstream phase consumes. One shape
regardless of source (extension | recorder | upload)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import CaptureSession, Event, Job, MediaAsset, Project
from app.queue import enqueue_understanding
from app.schemas import (
    AssetRegister,
    EventsIngest,
    EventsIngestOut,
    JobOut,
    SessionComplete,
    SessionCreate,
    SessionDetail,
    SessionOut,
    SessionStatus,
    SessionTrim,
    UploadTargetOut,
)
from app.storage import store

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _get_session_or_404(db: Session, session_id: str) -> CaptureSession:
    obj = db.get(CaptureSession, session_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="session not found")
    return obj


def _poster_for(db: Session, session_id: str) -> str | None:
    """A representative thumbnail: earliest extracted frame, else first screenshot."""
    frame = db.scalar(
        select(MediaAsset)
        .where(MediaAsset.session_id == session_id, MediaAsset.kind == "frame")
        .order_by(MediaAsset.id)
    )
    if frame:
        return frame.storage_key
    shot = db.scalar(
        select(MediaAsset)
        .where(MediaAsset.session_id == session_id, MediaAsset.kind == "screenshot")
        .order_by(MediaAsset.id)
    )
    return shot.storage_key if shot else None


def _session_out(db: Session, sess: CaptureSession) -> SessionOut:
    out = SessionOut.model_validate(sess)
    out.poster = _poster_for(db, sess.id)
    return out


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate, db: Session = Depends(get_session)) -> CaptureSession:
    if db.get(Project, payload.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    sess = CaptureSession(
        project_id=payload.project_id,
        source_type=payload.source_type,
        telemetry="absent",
        status="created",
        viewport_json=payload.viewport.model_dump() if payload.viewport else None,
    )
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


@router.post("/{session_id}/assets", response_model=UploadTargetOut)
def register_asset(
    session_id: str, payload: AssetRegister, db: Session = Depends(get_session)
) -> UploadTargetOut:
    """Register a media asset and return a presigned-style upload target.
    Local storage returns an API PUT route; S3/MinIO would return a real presigned URL."""
    sess = _get_session_or_404(db, session_id)
    asset = MediaAsset(session_id=sess.id, kind=payload.kind, storage_key="", meta_json=payload.meta)
    db.add(asset)
    db.flush()  # get asset.id
    storage_key = f"sessions/{sess.id}/{payload.kind}_{asset.id}.{payload.ext}"
    asset.storage_key = storage_key
    db.commit()
    target = store.upload_target(storage_key)
    return UploadTargetOut(asset_id=asset.id, storage_key=target.storage_key, url=target.url)


@router.post("/{session_id}/events", response_model=EventsIngestOut)
def ingest_events(
    session_id: str, payload: EventsIngest, db: Session = Depends(get_session)
) -> EventsIngestOut:
    sess = _get_session_or_404(db, session_id)
    for e in payload.events:
        db.add(
            Event(
                session_id=sess.id,
                seq=e.seq,
                type=e.type,
                t_ms=e.t_ms,
                selector=e.selector,
                text=e.text,
                bbox_json=e.bbox,
                value_redacted=e.value_redacted,
            )
        )
    db.commit()
    return EventsIngestOut(ingested=len(payload.events))


@router.post("/{session_id}/complete", response_model=SessionOut)
def complete_session(
    session_id: str, payload: SessionComplete, db: Session = Depends(get_session)
) -> CaptureSession:
    sess = _get_session_or_404(db, session_id)
    event_count = db.scalar(
        select(func.count()).select_from(Event).where(Event.session_id == sess.id)
    )
    sess.telemetry = "present" if (event_count or 0) > 0 else "absent"
    sess.status = "captured"
    if payload.duration_ms is not None:
        sess.duration_ms = payload.duration_ms
    db.commit()
    db.refresh(sess)
    # Kick off the understanding pipeline (session -> Workflow Graph).
    enqueue_understanding(sess.id)
    return sess


@router.get("", response_model=list[SessionOut])
def list_sessions(
    project_id: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_session),
) -> list[SessionOut]:
    """List captures for a project, or all captures (Library) when project_id is omitted."""
    q = select(CaptureSession).order_by(CaptureSession.created_at.desc()).limit(limit)
    if project_id:
        q = q.where(CaptureSession.project_id == project_id)
    return [_session_out(db, s) for s in db.scalars(q)]


@router.get("/{session_id}/status", response_model=SessionStatus)
def get_session_status(session_id: str, db: Session = Depends(get_session)) -> SessionStatus:
    sess = _get_session_or_404(db, session_id)
    jobs = list(
        db.scalars(
            select(Job).where(Job.session_id == session_id).order_by(Job.version, Job.updated_at)
        )
    )
    latest_version = db.scalar(select(func.max(Job.version)).where(Job.session_id == session_id))
    return SessionStatus(
        session_id=sess.id,
        status=sess.status,
        latest_version=latest_version,
        jobs=[JobOut.model_validate(j) for j in jobs if j.version == (latest_version or 0)],
    )


@router.post("/{session_id}/reprocess", response_model=SessionOut)
def reprocess_session(session_id: str, db: Session = Depends(get_session)) -> CaptureSession:
    sess = _get_session_or_404(db, session_id)
    enqueue_understanding(sess.id)
    return sess


@router.patch("/{session_id}/trim", response_model=SessionOut)
def set_trim(
    session_id: str, payload: SessionTrim, db: Session = Depends(get_session)
) -> CaptureSession:
    """Set an in/out trim window and re-run understanding on just that region."""
    sess = _get_session_or_404(db, session_id)
    if payload.end_ms <= payload.start_ms:
        raise HTTPException(status_code=400, detail="end_ms must be greater than start_ms")
    sess.trim_start_ms = payload.start_ms
    sess.trim_end_ms = payload.end_ms
    db.commit()
    db.refresh(sess)
    enqueue_understanding(sess.id)
    return sess


class KeepRangesReq(BaseModel):
    ranges: list[list[int]]  # [[startMs, endMs], …]


@router.post("/{session_id}/keep-ranges", response_model=SessionOut)
def set_keep_ranges(
    session_id: str, payload: KeepRangesReq, db: Session = Depends(get_session)
) -> CaptureSession:
    """Keep only these time ranges (from split/delete) and re-run understanding."""
    sess = _get_session_or_404(db, session_id)
    ranges = [[int(a), int(b)] for a, b in payload.ranges if b > a]
    sess.keep_ranges_json = ranges or None
    sess.trim_start_ms = None
    sess.trim_end_ms = None
    db.commit()
    db.refresh(sess)
    enqueue_understanding(sess.id)
    return sess


@router.get("/{session_id}", response_model=SessionDetail)
def get_session_detail(session_id: str, db: Session = Depends(get_session)) -> SessionDetail:
    sess = _get_session_or_404(db, session_id)
    event_count = db.scalar(
        select(func.count()).select_from(Event).where(Event.session_id == sess.id)
    )
    detail = SessionDetail.model_validate(sess)  # assets filled from the relationship
    detail.event_count = event_count or 0
    detail.poster = _poster_for(db, sess.id)
    return detail
