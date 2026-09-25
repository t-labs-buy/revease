"""Documentation API — generate (async, in the worker), read, edit, re-grab a
step's snapshot, export MD/PDF/DOCX.

Why generation is asynchronous: snapshots are grabbed from the source video with
ffmpeg, which only the worker has. The API bumps `Document.doc_version`, marks
the row queued and enqueues by task name; the web polls GET until `ready`.

Why GET no longer builds a mechanical doc on demand: the mechanical text was
never good enough to ship, and a lazily-created row hid the "Generate" call to
action. With no row GET answers `status: "none"`; the public share route keeps a
mechanical fallback so old links still resolve.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.auth import CurrentUser
from app.db import get_session
from app.docgen import DOCX_MEDIA_TYPE, render_docx, render_markdown, render_pdf, slugify, upgrade_doc
from app.models import CaptureSession, Document, MediaAsset, Skill, WorkflowGraphRow
from app.ownership import owned_project, owned_row
from app.queue import enqueue_document_generate, enqueue_document_snapshot
from app.schemas import DocGenerateIn, DocPatchIn, DocSnapshotIn, DocumentOut

router = APIRouter(tags=["documents"])

GENERATING = ("queued", "running")
# A queued/running row older than this is presumed orphaned (worker died) and
# may be re-enqueued.
STUCK_AFTER = timedelta(minutes=15)


def _latest_graph(db: Session, project_id: str) -> WorkflowGraphRow:
    row = db.scalar(
        select(WorkflowGraphRow)
        .where(WorkflowGraphRow.project_id == project_id)
        .order_by(WorkflowGraphRow.version.desc())
    )
    if row is None:
        raise HTTPException(status_code=404, detail="no workflow graph yet — process a capture first")
    return row


def _doc_row(db: Session, project_id: str) -> Document | None:
    return db.scalar(select(Document).where(Document.project_id == project_id))


def _session_ids(db: Session, project_id: str) -> list[str]:
    return list(db.scalars(select(CaptureSession.id).where(CaptureSession.project_id == project_id)))


def _has_video(db: Session, project_id: str) -> bool:
    sids = _session_ids(db, project_id)
    if not sids:
        return False
    return (
        db.scalar(
            select(MediaAsset.id).where(MediaAsset.session_id.in_(sids), MediaAsset.kind == "raw_video")
        )
        is not None
    )


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite drops the zone


def _out(row: Document | None, project_id: str, latest_graph_version: int) -> DocumentOut:
    if row is None:
        return DocumentOut(
            document_id=None,
            project_id=project_id,
            graph_version=None,
            doc=None,
            status="none",
            latest_graph_version=latest_graph_version,
        )
    return DocumentOut(
        document_id=row.id,
        project_id=project_id,
        graph_version=row.graph_version,
        doc=row.doc_json or None,
        status=row.status or "ready",
        doc_version=row.doc_version or 0,
        latest_graph_version=latest_graph_version,
        stale=row.status == "ready" and row.graph_version != latest_graph_version,
        error=row.error_json,
        progress=row.progress,
        message=row.message,
    )


def _upgrade_in_place(db: Session, row: Document, graph: WorkflowGraphRow) -> None:
    """One-time migration of a legacy v1 row, done on read so nothing else has to know."""
    if not row.doc_json or row.doc_json.get("version") == 2:
        return
    aligned_graph = graph.graph_json if row.graph_version == graph.version else None
    row.doc_json = upgrade_doc(row.doc_json, aligned_graph)
    flag_modified(row, "doc_json")
    db.commit()
    db.refresh(row)


@router.get("/projects/{project_id}/document", response_model=DocumentOut)
def get_document(project_id: str, user: CurrentUser, db: Session = Depends(get_session)) -> DocumentOut:
    owned_project(db, user, project_id)
    graph = _latest_graph(db, project_id)
    row = _doc_row(db, project_id)
    if row is not None:
        _upgrade_in_place(db, row, graph)
    return _out(row, project_id, graph.version)


@router.post("/projects/{project_id}/document/generate", response_model=DocumentOut, status_code=202)
def generate_document(
    project_id: str,
    user: CurrentUser,
    payload: DocGenerateIn = DocGenerateIn(),
    db: Session = Depends(get_session),
) -> DocumentOut:
    owned_project(db, user, project_id)
    graph = _latest_graph(db, project_id)
    if not _has_video(db, project_id):
        raise HTTPException(status_code=409, detail="no source video — snapshots need the recording")
    if payload.skill_id:
        skill = owned_row(db, user, Skill, payload.skill_id, "skill")
        if skill.target != "doc":
            raise HTTPException(status_code=400, detail="that skill is for videos, not documents")

    row = _doc_row(db, project_id)
    now = datetime.now(timezone.utc)
    if row is not None and row.status in GENERATING:
        updated = _utc(row.updated_at) or now
        if now - updated < STUCK_AFTER:
            return _out(row, project_id, graph.version)  # already on its way; don't double-enqueue

    if row is None:
        row = Document(project_id=project_id, graph_version=graph.version, doc_json={}, status="queued",
                       doc_version=1, progress=0.0, message="Waiting for a worker…")
        db.add(row)
    else:
        # keep doc_json: the previous document keeps serving while the new one is written
        row.status = "queued"
        row.doc_version = (row.doc_version or 0) + 1
        row.error_json = None
        row.progress = 0.0
        row.message = "Waiting for a worker…"
    db.commit()
    db.refresh(row)
    enqueue_document_generate(project_id, row.doc_version, payload.skill_id, payload.instruction)
    return _out(row, project_id, graph.version)


@router.patch("/projects/{project_id}/document", response_model=DocumentOut)
def save_document(
    project_id: str, payload: DocPatchIn, user: CurrentUser, db: Session = Depends(get_session)
) -> DocumentOut:
    owned_project(db, user, project_id)
    graph = _latest_graph(db, project_id)
    row = _doc_row(db, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no document yet — generate one first")
    if row.status in GENERATING:
        raise HTTPException(status_code=409, detail="document is being generated — try again shortly")

    doc = payload.doc.model_dump()
    # A doc may only reference this project's media (media GET is public, and a
    # stored key is served on share links).
    allowed = tuple(f"sessions/{sid}/" for sid in _session_ids(db, project_id))
    for step in doc["steps"]:
        snap = step.get("snapshot") or {}
        for k in (snap.get("key"), snap.get("raw_key")):
            if k and not k.startswith(allowed):
                raise HTTPException(status_code=422, detail=f"snapshot {k!r} does not belong to this project")

    previous = (row.doc_json or {}).get("meta") or {}
    doc["meta"] = {
        **doc.get("meta", {}),
        "writer": previous.get("writer", doc["meta"].get("writer")),
        "model": previous.get("model"),
        "generated_at": previous.get("generated_at"),
        "graph_version": row.graph_version,
        "edited_at": datetime.now(timezone.utc).isoformat(),
    }
    row.doc_json = doc
    flag_modified(row, "doc_json")
    db.commit()
    db.refresh(row)
    return _out(row, project_id, graph.version)


@router.post(
    "/projects/{project_id}/document/steps/{step_id}/snapshot",
    response_model=DocumentOut,
    status_code=202,
)
def regrab_snapshot(
    project_id: str,
    step_id: str,
    payload: DocSnapshotIn,
    user: CurrentUser,
    db: Session = Depends(get_session),
) -> DocumentOut:
    owned_project(db, user, project_id)
    graph = _latest_graph(db, project_id)
    row = _doc_row(db, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no document yet — generate one first")
    if row.status in GENERATING:
        raise HTTPException(status_code=409, detail="document is being generated — try again shortly")
    if not _has_video(db, project_id):
        raise HTTPException(status_code=409, detail="no source video to grab a frame from")

    steps = (row.doc_json or {}).get("steps") or []
    step = next((s for s in steps if s.get("id") == step_id), None)
    if step is None:
        raise HTTPException(status_code=404, detail="no such step in this document")
    snap = dict(step.get("snapshot") or {})
    snap.setdefault("key", None)
    snap.setdefault("raw_key", None)
    snap["pending"] = True
    step["snapshot"] = snap
    flag_modified(row, "doc_json")
    db.commit()
    db.refresh(row)
    enqueue_document_snapshot(project_id, step_id, payload.t)
    return _out(row, project_id, graph.version)


@router.get("/projects/{project_id}/document/export")
def export_document(
    project_id: str,
    request: Request,
    user: CurrentUser,
    format: str = Query(default="md", pattern="^(md|pdf|docx)$"),
    db: Session = Depends(get_session),
) -> Response:
    owned_project(db, user, project_id)
    graph = _latest_graph(db, project_id)
    row = _doc_row(db, project_id)
    if row is None or not row.doc_json:
        raise HTTPException(status_code=404, detail="no document yet — generate one first")
    _upgrade_in_place(db, row, graph)
    doc = row.doc_json
    name = slugify(doc.get("title", "document"))
    if format == "md":
        base = str(request.base_url).rstrip("/")
        return Response(
            content=render_markdown(doc, media_base=base).encode("utf-8"),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{name}.md"'},
        )
    if format == "docx":
        return Response(
            content=render_docx(doc),
            media_type=DOCX_MEDIA_TYPE,
            headers={"Content-Disposition": f'attachment; filename="{name}.docx"'},
        )
    return Response(
        content=render_pdf(doc),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'},
    )
