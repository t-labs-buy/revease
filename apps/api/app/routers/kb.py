"""Knowledge Base — searchable, shareable guides/docs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db import get_session
from app.models import KbArticle
from app.ownership import owned_project, owned_row

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
def list_articles(
    user: CurrentUser,
    scope: str = Query(default="mine", pattern="^(mine|all)$"),
    db: Session = Depends(get_session),
) -> list[ArticleOut]:
    q = select(KbArticle).order_by(KbArticle.created_at.desc())
    if not (scope == "all" and user.is_admin):
        q = q.where(KbArticle.user_id == user.id)
    return [_out(a) for a in db.scalars(q)]


@router.get("/{article_id}", response_model=ArticleOut)
def get_article(
    article_id: str, user: CurrentUser, db: Session = Depends(get_session)
) -> ArticleOut:
    return _out(owned_row(db, user, KbArticle, article_id, "article"))


@router.post("", response_model=ArticleOut)
def create_article(
    payload: ArticleIn, user: CurrentUser, db: Session = Depends(get_session)
) -> ArticleOut:
    # An article may reference a project, but only one the caller owns.
    if payload.project_id:
        owned_project(db, user, payload.project_id)
    a = KbArticle(
        user_id=user.id,
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
def delete_article(
    article_id: str, user: CurrentUser, db: Session = Depends(get_session)
) -> dict:
    db.delete(owned_row(db, user, KbArticle, article_id, "article"))
    db.commit()
    return {"ok": True}
