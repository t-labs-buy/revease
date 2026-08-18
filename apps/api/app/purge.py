"""One-shot cleanup of ownerless rows left over from the pre-auth, single-user era.

Every project/skill/article/brand-package created before per-user spaces existed
has `user_id IS NULL`, which means it belongs to no account and is invisible to
every user. This deletes those rows (and, for projects, everything beneath them
plus their media on disk).

Destructive and not reversible — back up data/refract.sqlite3 first. Run with:

    cd apps/api && uv run python -m app.purge          # show what would go
    cd apps/api && uv run python -m app.purge --yes    # actually delete
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import BrandPackage, KbArticle, Project, Skill
from app.ownership import delete_project_cascade, purge_media

_DIRECT_MODELS = (Skill, KbArticle, BrandPackage)


def count_ownerless() -> dict[str, int]:
    init_db()
    db = SessionLocal()
    try:
        counts = {
            "projects": len(list(db.scalars(select(Project).where(Project.user_id.is_(None)))))
        }
        for model in _DIRECT_MODELS:
            rows = db.scalars(select(model).where(model.user_id.is_(None)))
            counts[model.__tablename__] = len(list(rows))
        return counts
    finally:
        db.close()


def purge_ownerless() -> dict[str, int]:
    """Delete every ownerless row. Returns what was removed."""
    init_db()
    db = SessionLocal()
    removed = {"projects": 0}
    try:
        # Projects first: cascade their sessions/graphs/videos/docs/shares/jobs.
        media_keys: list[tuple[list[str], list[str]]] = []
        for project in db.scalars(select(Project).where(Project.user_id.is_(None))):
            media_keys.append(delete_project_cascade(db, project))
            removed["projects"] += 1

        for model in _DIRECT_MODELS:
            rows = list(db.scalars(select(model).where(model.user_id.is_(None))))
            for row in rows:
                db.delete(row)
            removed[model.__tablename__] = len(rows)

        db.commit()
        # Only once the DB delete has committed do we touch the filesystem.
        for sess_ids, vp_ids in media_keys:
            purge_media(sess_ids, vp_ids)
    finally:
        db.close()
    return removed


if __name__ == "__main__":
    counts = count_ownerless()
    total = sum(counts.values())
    if total == 0:
        print("nothing ownerless to purge")
        raise SystemExit(0)
    print("ownerless rows:", counts)
    if "--yes" not in sys.argv:
        print("\ndry run — re-run with --yes to delete these permanently")
        raise SystemExit(0)
    print("purged:", purge_ownerless())
