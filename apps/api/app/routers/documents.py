"""Step-by-step doc (SOP) API — generate from the graph, view, export MD/PDF."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db import get_session
from app.docgen import build_document, render_markdown, render_pdf, slugify
from app.models import Document, WorkflowGraphRow
from app.ownership import owned_project
from app.schemas import DocumentOut

router = APIRouter(tags=["documents"])


class DocStyleReq(BaseModel):
    instruction: str | None = None


def _latest_graph(db: Session, project_id: str) -> WorkflowGraphRow:
    row = db.scalar(
        select(WorkflowGraphRow)
        .where(WorkflowGraphRow.project_id == project_id)
        .order_by(WorkflowGraphRow.version.desc())
    )
    if row is None:
        raise HTTPException(status_code=404, detail="no workflow graph yet — process a capture first")
    return row


def _get_or_build(db: Session, user, project_id: str) -> Document:
    """Ownership is checked here so every route that reads a doc inherits it."""
    owned_project(db, user, project_id)
    graph = _latest_graph(db, project_id)
    doc = db.scalar(select(Document).where(Document.project_id == project_id))
    if doc is None or doc.graph_version != graph.version:
        built = build_document(graph.graph_json)
        if doc is None:
            doc = Document(project_id=project_id, graph_version=graph.version, doc_json=built)
            db.add(doc)
        else:
            doc.graph_version = graph.version
            doc.doc_json = built
        db.commit()
        db.refresh(doc)
    return doc


@router.get("/projects/{project_id}/document", response_model=DocumentOut)
def get_document(
    project_id: str, user: CurrentUser, db: Session = Depends(get_session)
) -> DocumentOut:
    doc = _get_or_build(db, user, project_id)
    return DocumentOut(
        document_id=doc.id,
        project_id=project_id,
        graph_version=doc.graph_version,
        doc=doc.doc_json,
    )


@router.post("/projects/{project_id}/document", response_model=DocumentOut)
def regenerate_document(
    project_id: str,
    user: CurrentUser,
    payload: DocStyleReq = DocStyleReq(),
    db: Session = Depends(get_session),
) -> DocumentOut:
    owned_project(db, user, project_id)
    graph = _latest_graph(db, project_id)
    doc = db.scalar(select(Document).where(Document.project_id == project_id))
    built = build_document(graph.graph_json)
    if payload.instruction:
        from app.rewrite import restyle_doc

        built["steps"] = restyle_doc(built.get("steps", []), payload.instruction)
    if doc is None:
        doc = Document(project_id=project_id, graph_version=graph.version, doc_json=built)
        db.add(doc)
    else:
        doc.graph_version = graph.version
        doc.doc_json = built
    db.commit()
    db.refresh(doc)
    return DocumentOut(
        document_id=doc.id, project_id=project_id, graph_version=doc.graph_version, doc=doc.doc_json
    )


@router.get("/projects/{project_id}/document/export")
def export_document(
    project_id: str,
    request: Request,
    user: CurrentUser,
    format: str = Query(default="md", pattern="^(md|pdf)$"),
    db: Session = Depends(get_session),
) -> Response:
    doc = _get_or_build(db, user, project_id).doc_json
    name = slugify(doc.get("title", "document"))
    if format == "md":
        base = str(request.base_url).rstrip("/")
        body = render_markdown(doc, media_base=base).encode("utf-8")
        return Response(
            content=body,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{name}.md"'},
        )
    pdf = render_pdf(doc)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'},
    )
