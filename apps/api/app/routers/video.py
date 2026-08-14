"""Studio video editor API: edit-spec CRUD + render trigger. Render happens only
on export (a Celery job); preview is client-side."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from pydantic import BaseModel

from app.db import get_session
from app.diff import migrate_edit_spec
from app.editspec import build_edit_spec, mark_dirty, voice_timeline_key, voice_track_key
from app.models import CaptureSession, MediaAsset, RenderJob, VideoProject, WorkflowGraphRow
from app.queue import enqueue_render, enqueue_voice_track
from app.schemas import EditSpecPatch, RenderJobOut, VideoSpecOut
from app.storage import store

router = APIRouter(tags=["video"])


def _latest_graph(db: Session, project_id: str) -> WorkflowGraphRow | None:
    return db.scalar(
        select(WorkflowGraphRow)
        .where(WorkflowGraphRow.project_id == project_id)
        .order_by(WorkflowGraphRow.version.desc())
    )


def _source_video(db: Session, project_id: str) -> str | None:
    asset = db.scalar(
        select(MediaAsset)
        .join(CaptureSession, CaptureSession.id == MediaAsset.session_id)
        .where(CaptureSession.project_id == project_id, MediaAsset.kind == "raw_video")
        .order_by(CaptureSession.created_at.desc())
    )
    return asset.storage_key if asset else None


def _latest_viewport(db: Session, project_id: str) -> dict | None:
    sess = db.scalar(
        select(CaptureSession)
        .where(CaptureSession.project_id == project_id)
        .order_by(CaptureSession.created_at.desc())
    )
    return sess.viewport_json if sess else None


def _get_or_build(db: Session, project_id: str) -> VideoProject:
    vp = db.scalar(select(VideoProject).where(VideoProject.project_id == project_id))
    graph = _latest_graph(db, project_id)
    if graph is None:
        raise HTTPException(status_code=404, detail="no workflow graph yet — process a capture first")
    if vp is None:
        spec = build_edit_spec(graph.graph_json, _latest_viewport(db, project_id))
        vp = VideoProject(project_id=project_id, graph_version=graph.version, edit_spec_json=spec)
        db.add(vp)
        db.commit()
        db.refresh(vp)
    elif vp.graph_version != graph.version:
        # Project memory: a re-record produced a newer graph. Carry the user's edits
        # onto unchanged steps; only added/changed steps are marked dirty.
        old_graph = db.scalar(
            select(WorkflowGraphRow).where(
                WorkflowGraphRow.project_id == project_id,
                WorkflowGraphRow.version == vp.graph_version,
            )
        )
        if old_graph is not None:
            vp.edit_spec_json = migrate_edit_spec(
                vp.edit_spec_json, old_graph.graph_json, graph.graph_json,
                _latest_viewport(db, project_id),
            )
        else:
            vp.edit_spec_json = build_edit_spec(graph.graph_json, _latest_viewport(db, project_id))
        vp.graph_version = graph.version
        db.commit()
        db.refresh(vp)
    return vp


@router.get("/projects/{project_id}/video", response_model=VideoSpecOut)
def get_video(project_id: str, db: Session = Depends(get_session)) -> VideoSpecOut:
    vp = _get_or_build(db, project_id)
    return VideoSpecOut(
        video_project_id=vp.id,
        project_id=project_id,
        graph_version=vp.graph_version,
        edit_spec=vp.edit_spec_json,
        source_video=_source_video(db, project_id),
    )


@router.patch("/projects/{project_id}/video", response_model=VideoSpecOut)
def patch_video(
    project_id: str, payload: EditSpecPatch, db: Session = Depends(get_session)
) -> VideoSpecOut:
    vp = _get_or_build(db, project_id)
    new_spec = mark_dirty(vp.edit_spec_json, payload.edit_spec)
    vp.edit_spec_json = new_spec
    db.commit()
    db.refresh(vp)
    return VideoSpecOut(
        video_project_id=vp.id,
        project_id=project_id,
        graph_version=vp.graph_version,
        edit_spec=vp.edit_spec_json,
        source_video=_source_video(db, project_id),
    )


@router.post("/projects/{project_id}/video/render", response_model=RenderJobOut)
def render_video(project_id: str, db: Session = Depends(get_session)) -> RenderJobOut:
    vp = _get_or_build(db, project_id)
    job = RenderJob(video_project_id=vp.id, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    enqueue_render(job.id)
    return RenderJobOut(id=job.id, status=job.status)


class VoiceTrackReq(BaseModel):
    voice_id: str
    speed: float = 1.0


@router.post("/projects/{project_id}/voice-track")
def start_voice_track(
    project_id: str, payload: VoiceTrackReq, db: Session = Depends(get_session)
) -> dict:
    """Kick off (once) building the narration preview track. Poll the GET for readiness.
    The key is content-hashed on the script, so editing the script rebuilds it."""
    vp = _get_or_build(db, project_id)
    key = voice_track_key(project_id, payload.voice_id, payload.speed, vp.edit_spec_json)
    tkey = voice_timeline_key(project_id, payload.voice_id, payload.speed, vp.edit_spec_json)
    if store.exists(key):
        return {
            "url": store.download_url(key),
            "ready": True,
            "timeline_url": store.download_url(tkey) if store.exists(tkey) else None,
        }
    enqueue_voice_track(project_id, payload.voice_id, payload.speed)
    return {"url": store.download_url(key), "ready": False, "timeline_url": None}


@router.get("/projects/{project_id}/voice-track")
def voice_track_status(
    project_id: str, voice_id: str, speed: float = 1.0, db: Session = Depends(get_session)
) -> dict:
    """Poll-only readiness check — does NOT re-enqueue (avoids flooding the worker)."""
    vp = _get_or_build(db, project_id)
    key = voice_track_key(project_id, voice_id, speed, vp.edit_spec_json)
    tkey = voice_timeline_key(project_id, voice_id, speed, vp.edit_spec_json)
    ready = store.exists(key)
    return {
        "url": store.download_url(key),
        "ready": ready,
        "timeline_url": store.download_url(tkey) if ready and store.exists(tkey) else None,
    }


@router.get("/render/{job_id}", response_model=RenderJobOut)
def get_render(job_id: str, db: Session = Depends(get_session)) -> RenderJobOut:
    job = db.get(RenderJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="render job not found")
    return RenderJobOut(
        id=job.id,
        status=job.status,
        output_key=job.output_key,
        output_url=store.download_url(job.output_key) if job.output_key else None,
        stats_json=job.stats_json,
        error_json=job.error_json,
    )
