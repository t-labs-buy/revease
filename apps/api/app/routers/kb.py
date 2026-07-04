"""Knowledge Base — searchable, shareable guides/docs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import KbArticle

router = APIRouter(prefix="/kb", tags=["kb"])


class ArticleIn(BaseModel):
    title: str
    summary: str = ""
    body_md: str = ""
    tags: list[str] = Field(default_factory=list)
    project_id: str | None = None


class ArticleOut(BaseModel):
    id: str
    title: str
    summary: str
    body_md: str
    tags: list[str]
    project_id: str | None = None


def _out(a: KbArticle) -> ArticleOut:
    return ArticleOut(
        id=a.id,
        title=a.title,
        summary=a.summary,
        body_md=a.body_md,
        tags=a.tags_json or [],
        project_id=a.project_id,
    )


@router.get("", response_model=list[ArticleOut])
def list_articles(db: Session = Depends(get_session)) -> list[ArticleOut]:
    rows = db.scalars(select(KbArticle).order_by(KbArticle.created_at.desc()))
    return [_out(a) for a in rows]


@router.get("/{article_id}", response_model=ArticleOut)
def get_article(article_id: str, db: Session = Depends(get_session)) -> ArticleOut:
    a = db.get(KbArticle, article_id)
    if a is None:
        raise HTTPException(status_code=404, detail="article not found")
    return _out(a)


@router.post("", response_model=ArticleOut)
def create_article(payload: ArticleIn, db: Session = Depends(get_session)) -> ArticleOut:
    a = KbArticle(
        title=payload.title.strip() or "Untitled",
        summary=payload.summary,
        body_md=payload.body_md,
        tags_json=payload.tags,
        project_id=payload.project_id,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return _out(a)


@router.delete("/{article_id}")
def delete_article(article_id: str, db: Session = Depends(get_session)) -> dict:
    a = db.get(KbArticle, article_id)
    if a:
        db.delete(a)
        db.commit()
    return {"ok": True}
