"""Workflow Graph fetch — the canonical IR every generator (docs, video) reads."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.diff import diff_graphs
from app.models import WorkflowGraphRow
from app.schemas import GraphOut

router = APIRouter(prefix="/projects", tags=["graphs"])


@router.get("/{project_id}/graph", response_model=GraphOut)
def get_graph(
    project_id: str, version: int | None = Query(default=None), db: Session = Depends(get_session)
) -> WorkflowGraphRow:
    q = select(WorkflowGraphRow).where(WorkflowGraphRow.project_id == project_id)
    if version is not None:
        q = q.where(WorkflowGraphRow.version == version)
    else:
        q = q.order_by(WorkflowGraphRow.version.desc())
    row = db.scalar(q)
    if row is None:
        raise HTTPException(status_code=404, detail="no graph for project")
    return row


@router.get("/{project_id}/memory")
def get_memory(project_id: str, db: Session = Depends(get_session)) -> dict:
    """Project memory: diff the two most recent graph versions (re-record diff)."""
    versions = list(
        db.scalars(
            select(WorkflowGraphRow)
            .where(WorkflowGraphRow.project_id == project_id)
            .order_by(WorkflowGraphRow.version.desc())
            .limit(2)
        )
    )
    if not versions:
        raise HTTPException(status_code=404, detail="no graph for project")
    if len(versions) < 2:
        return {
            "has_prior": False,
            "to_version": versions[0].version,
            "summary": {"added": len(versions[0].graph_json.get("steps", [])),
                        "changed": 0, "unchanged": 0, "removed": 0},
            "steps": [],
            "removed": [],
        }
    new, old = versions[0], versions[1]
    return {"has_prior": True, **diff_graphs(old.graph_json, new.graph_json)}
