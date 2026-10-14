"""AI script-rewrite endpoint — rewrites narration lines via Claude."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db import get_session
from app.editspec import spoken_text
from app.ownership import owned_project
from app.rewrite import generate_script, rewrite_lines, suggest_zooms_with_source
from app.usage_tracking import current as usage, tracked

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
    # "anthropic:…" / "openrouter:…" when the AI answered, "rules" for the
    # rule-based fallback (no key configured, or the AI call failed)
    source: str = "none"


@router.post("/projects/{project_id}/rewrite", response_model=RewriteOut)
@tracked("ai_assist", "rewrite_script", "script.rewritten", "project", entity_id="project_id")
def rewrite(
    project_id: str, payload: RewriteReq, user: CurrentUser, db: Session = Depends(get_session)
) -> RewriteOut:
    owned_project(db, user, project_id)
    if not payload.lines:
        usage().skip()
        return RewriteOut(lines=[])
    usage().item_count(len(payload.lines)).set(custom_instruction=bool(payload.instruction))
    try:
        # Pause markers are timing, not words: the model would read them as text.
        lines = [spoken_text(ln) for ln in payload.lines]
        return RewriteOut(lines=rewrite_lines(lines, payload.instruction))
    except Exception as e:  # surface a clean message to the editor
        raise HTTPException(status_code=502, detail=f"AI rewrite failed: {e}")


@router.post("/projects/{project_id}/generate-script", response_model=RewriteOut)
@tracked("ai_assist", "generate_script", "script.generated", "project", entity_id="project_id")
def generate(
    project_id: str, payload: GenReq, user: CurrentUser, db: Session = Depends(get_session)
) -> RewriteOut:
    owned_project(db, user, project_id)
    if not payload.scenes:
        usage().skip()
        return RewriteOut(lines=[])
    usage().item_count(len(payload.scenes)).set(custom_instruction=bool(payload.instruction))
    try:
        scenes = [
            {**sc, "narration": spoken_text(str(sc.get("narration") or ""))} for sc in payload.scenes
        ]
        return RewriteOut(lines=generate_script(scenes, payload.title, payload.instruction))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI script generation failed: {e}")


@router.post("/projects/{project_id}/suggest-zooms", response_model=ZoomOut)
@tracked("ai_assist", "suggest_zooms", "zooms.suggested", "project", entity_id="project_id")
def suggest(
    project_id: str, payload: ZoomReq, user: CurrentUser, db: Session = Depends(get_session)
) -> ZoomOut:
    owned_project(db, user, project_id)
    if not payload.scenes:
        usage().skip()
        return ZoomOut(zooms=[])
    zooms, source = suggest_zooms_with_source(payload.scenes)
    usage().item_count(len(zooms)).set(engine=source.split(":", 1)[0])
    return ZoomOut(zooms=zooms, source=source)
