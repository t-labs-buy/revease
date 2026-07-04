"""Skills — reusable generation presets (voice/tone/aspect/captions/zoom) that
shape how AI produces a Video or Doc."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Skill

router = APIRouter(prefix="/skills", tags=["skills"])


class GenSkillReq(BaseModel):
    prompt: str
    target: str = "doc"


class SkillIn(BaseModel):
    name: str
    description: str = ""
    target: str = "video"  # "video" | "doc"
    settings: dict = Field(default_factory=dict)


class SkillOut(BaseModel):
    id: str
    name: str
    description: str
    target: str
    settings: dict


def _out(s: Skill) -> SkillOut:
    return SkillOut(
        id=s.id, name=s.name, description=s.description, target=s.target, settings=s.settings_json or {}
    )


@router.get("", response_model=list[SkillOut])
def list_skills(db: Session = Depends(get_session)) -> list[SkillOut]:
    rows = db.scalars(select(Skill).order_by(Skill.created_at.desc()))
    return [_out(s) for s in rows]


@router.post("/generate", response_model=SkillOut)
def generate(payload: GenSkillReq, db: Session = Depends(get_session)) -> SkillOut:
    """AI-assistant: design a skill from a description (constrained to tool capabilities)."""
    if not payload.prompt.strip():
        raise HTTPException(status_code=400, detail="describe the skill you want")
    try:
        from app.rewrite import generate_skill

        built = generate_skill(payload.prompt, payload.target)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI skill builder failed: {e}")
    s = Skill(
        name=built["name"],
        description=built["description"],
        target=built["target"],
        settings_json=built["settings"],
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _out(s)


@router.get("/{skill_id}", response_model=SkillOut)
def get_skill(skill_id: str, db: Session = Depends(get_session)) -> SkillOut:
    s = db.get(Skill, skill_id)
    if s is None:
        raise HTTPException(status_code=404, detail="skill not found")
    return _out(s)


@router.put("/{skill_id}", response_model=SkillOut)
def update_skill(skill_id: str, payload: SkillIn, db: Session = Depends(get_session)) -> SkillOut:
    s = db.get(Skill, skill_id)
    if s is None:
        raise HTTPException(status_code=404, detail="skill not found")
    s.name = payload.name.strip() or s.name
    s.description = payload.description
    s.target = payload.target if payload.target in ("video", "doc") else s.target
    s.settings_json = payload.settings
    db.commit()
    db.refresh(s)
    return _out(s)


@router.post("", response_model=SkillOut)
def create_skill(payload: SkillIn, db: Session = Depends(get_session)) -> SkillOut:
    s = Skill(
        name=payload.name.strip() or "Untitled skill",
        description=payload.description,
        target=payload.target if payload.target in ("video", "doc") else "video",
        settings_json=payload.settings,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _out(s)


@router.delete("/{skill_id}")
def delete_skill(skill_id: str, db: Session = Depends(get_session)) -> dict:
    s = db.get(Skill, skill_id)
    if s:
        db.delete(s)
        db.commit()
    return {"ok": True}
