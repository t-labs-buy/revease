"""Publish & share — public tokenized links to a rendered video or generated doc.

Creating, listing and revoking links is private to the owner; *redeeming* a link
(`GET /shares/{token}`) is deliberately public — an unguessable token is the whole
authorization model, and that is the point of a share link."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db import get_session
from app.docgen import build_document_v2, upgrade_doc
from app.models import Document, RenderJob, Share, VideoProject, WorkflowGraphRow
from app.ownership import owned_project, project_ids_for
from app.schemas import ShareCreate, SharePublic, ShareOut, ShareUpdate
from app.storage import store

router = APIRouter(tags=["shares"])


def _out(s: Share) -> ShareOut:
    return ShareOut(
        token=s.token, kind=s.kind, revoked=s.revoked,
        allow_download=bool(s.allow_download),
        created_at=s.created_at, project_id=s.project_id,
    )


def _owned_share(db: Session, user, token: str) -> Share:  # noqa: ANN001
    s = db.scalar(select(Share).where(Share.token == token))
    if s is None:
        raise HTTPException(status_code=404, detail="share not found")
    owned_project(db, user, s.project_id, owner_only=True)  # owner or admin only
    return s


def _latest_render_key(db: Session, project_id: str) -> str | None:
    vp = db.scalar(select(VideoProject).where(VideoProject.project_id == project_id))
    if vp is None:
        return None
    job = db.scalar(
        select(RenderJob)
        .where(RenderJob.video_project_id == vp.id, RenderJob.status == "done")
        .order_by(RenderJob.updated_at.desc())
    )
    return job.output_key if job and job.output_key else None


@router.post("/projects/{project_id}/share", response_model=ShareOut)
def create_share(
    project_id: str, payload: ShareCreate, user: CurrentUser, db: Session = Depends(get_session)
) -> ShareOut:
    owned_project(db, user, project_id, owner_only=True)  # public links are the owner's call
    if payload.kind == "video" and _latest_render_key(db, project_id) is None:
        raise HTTPException(status_code=400, detail="generate a video before sharing it")
    # reuse an existing active share of this kind if present
    existing = db.scalar(
        select(Share).where(
            Share.project_id == project_id, Share.kind == payload.kind, Share.revoked == False  # noqa: E712
        )
    )
    if existing:
        if payload.allow_download is not None and existing.allow_download != payload.allow_download:
            existing.allow_download = payload.allow_download
            db.commit()
        return _out(existing)
    share = Share(
        project_id=project_id, kind=payload.kind,
        allow_download=bool(payload.allow_download),
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return _out(share)


@router.get("/projects/{project_id}/shares", response_model=list[ShareOut])
def list_shares(
    project_id: str, user: CurrentUser, db: Session = Depends(get_session)
) -> list[ShareOut]:
    owned_project(db, user, project_id, owner_only=True)
    rows = db.scalars(
        select(Share).where(Share.project_id == project_id, Share.revoked == False)  # noqa: E712
    )
    return [_out(s) for s in rows]


@router.get("/shares", response_model=list[ShareOut])
def list_all_shares(
    user: CurrentUser,
    scope: str = Query(default="mine", pattern="^(mine|all)$"),
    db: Session = Depends(get_session),
) -> list[ShareOut]:
    rows = db.scalars(
        select(Share)
        .where(
            Share.revoked == False,  # noqa: E712
            Share.project_id.in_(project_ids_for(db, user, all_spaces=scope == "all")),
        )
        .order_by(Share.created_at.desc())
    )
    return [_out(s) for s in rows]


@router.patch("/shares/{token}", response_model=ShareOut)
def update_share(
    token: str, payload: ShareUpdate, user: CurrentUser, db: Session = Depends(get_session)
) -> ShareOut:
    """Owner/admin: toggle whether the public page offers a Download button."""
    s = _owned_share(db, user, token)
    s.allow_download = payload.allow_download
    db.commit()
    return _out(s)


@router.delete("/shares/{token}")
def revoke_share(token: str, user: CurrentUser, db: Session = Depends(get_session)) -> dict:
    s = _owned_share(db, user, token)  # only the owner (or an admin) can revoke a link
    s.revoked = True
    db.commit()
    return {"revoked": True}


@router.get("/shares/{token}", response_model=SharePublic)
def get_share(token: str, db: Session = Depends(get_session)) -> SharePublic:
    """Public — no auth. Returns the shared video URL or document."""
    s = db.scalar(select(Share).where(Share.token == token, Share.revoked == False))  # noqa: E712
    if s is None:
        raise HTTPException(status_code=404, detail="link not found or revoked")
    graph = db.scalar(
        select(WorkflowGraphRow)
        .where(WorkflowGraphRow.project_id == s.project_id)
        .order_by(WorkflowGraphRow.version.desc())
    )
    title = (graph.graph_json.get("title") if graph else None) or "Refract video"
    allow_download = bool(s.allow_download)
    if s.kind == "doc":
        if graph is None:
            raise HTTPException(status_code=404, detail="no document to share")
        # Prefer the stored (AI-written, possibly edited) document so share links
        # show what the owner sees; fall back to a mechanical build for projects
        # that never generated one.
        row = db.scalar(select(Document).where(Document.project_id == s.project_id))
        if row is not None and row.doc_json and row.status == "ready":
            doc = upgrade_doc(row.doc_json, graph.graph_json if row.graph_version == graph.version else None)
        else:
            doc = build_document_v2(graph.graph_json)
        return SharePublic(kind="doc", title=doc.get("title") or title, project_id=s.project_id,
                           allow_download=allow_download, doc=doc)
    key = _latest_render_key(db, s.project_id)
    if key is None:
        raise HTTPException(status_code=404, detail="no rendered video yet")
    return SharePublic(kind="video", title=title, project_id=s.project_id,
                       allow_download=allow_download, video_url=store.download_url(key))
