"""AI script-rewrite endpoint — rewrites narration lines via Claude."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.rewrite import generate_script, rewrite_lines, suggest_zooms

router = APIRouter(tags=["rewrite"])


class RewriteReq(BaseModel):
    lines: list[str]
    instruction: str | None = None


class RewriteOut(BaseModel):
    lines: list[str]


class GenReq(BaseModel):
    scenes: list[dict]
    title: str = "Product demo"
    instruction: str | None = None


class ZoomReq(BaseModel):
    scenes: list[dict]


class ZoomOut(BaseModel):
    zooms: list[dict]


@router.post("/projects/{project_id}/rewrite", response_model=RewriteOut)
def rewrite(project_id: str, payload: RewriteReq) -> RewriteOut:
    if not payload.lines:
        return RewriteOut(lines=[])
    try:
        return RewriteOut(lines=rewrite_lines(payload.lines, payload.instruction))
    except Exception as e:  # surface a clean message to the editor
        raise HTTPException(status_code=502, detail=f"AI rewrite failed: {e}")


@router.post("/projects/{project_id}/generate-script", response_model=RewriteOut)
def generate(project_id: str, payload: GenReq) -> RewriteOut:
    if not payload.scenes:
        return RewriteOut(lines=[])
    try:
        return RewriteOut(lines=generate_script(payload.scenes, payload.title, payload.instruction))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI script generation failed: {e}")


@router.post("/projects/{project_id}/suggest-zooms", response_model=ZoomOut)
def suggest(project_id: str, payload: ZoomReq) -> ZoomOut:
    if not payload.scenes:
        return ZoomOut(zooms=[])
    try:
        return ZoomOut(zooms=suggest_zooms(payload.scenes))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI zoom suggestion failed: {e}")
