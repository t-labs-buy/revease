"""Seed sample data so Skills / Knowledge Base have content to explore.

Content is per-user: `seed_for_user` runs once when an account registers, so each
new space starts with the canonical skill and the onboarding articles instead of
three empty pages. Idempotent — it only inserts what that user is missing."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models import KbArticle, Skill

# The single canonical skill: a product demo with automatic mouse/click zoom.
SAMPLE_SKILLS = [
    {
        "name": "Product Demo",
        "description": "Product walkthrough that auto-zooms on mouse clicks, with a clear AI voiceover.",
        "target": "video",
        "settings_json": {
            "voice_id": "af_sarah",
            "speed": 1.0,
            "aspect": "16:9",
            "captions": True,
            "motion_zoom": True,
            "instruction": "Rewrite as a clear, confident product demo narration: explain what each screen and action does and why it matters, in a friendly professional tone.",
        },
    },
]
# Skills we no longer ship — removed so only "Product Demo" remains.
_OLD_SAMPLE_NAMES = [
    "Quick Tutorial", "Formal SOP", "Social Reel",
    "Marketing Demo", "User Onboarding", "Sales Demo", "SOP", "Quick Guide", "FAQ-style",
]

SAMPLE_ARTICLES = [
    {
        "title": "Getting Started with RevEase",
        "summary": "Record or upload once, then generate a polished video or doc in minutes.",
        "tags_json": ["guide", "onboarding"],
        "body_md": (
            "# Getting Started\n\n"
            "1. **Record** your screen (or **Upload** an MP4/MOV) from the Home page.\n"
            "2. RevEase transcribes it and builds a **Workflow Graph** of the steps.\n"
            "3. Click **AI Generate** to open the editor.\n"
            "4. Edit the **Script**, pick an **AI Voice**, tune **Zooms**, then **Generate Video**.\n"
            "5. **Share** a public link or export the file.\n\n"
            "Everything you capture appears in your **Library**."
        ),
    },
    {
        "title": "How to Record a Clean Demo",
        "summary": "Tips for crisp audio and a script that matches your voice.",
        "tags_json": ["recording", "tips"],
        "body_md": (
            "# Recording Tips\n\n"
            "- Enable **microphone** (and *Share tab audio* if narrating a tab) so the "
            "transcript and AI voice have something to work with.\n"
            "- Speak in short, complete sentences — each becomes a scene.\n"
            "- Pause briefly between steps; idle stretches are trimmed automatically.\n"
            "- After processing, the project is **auto-named** from what you said."
        ),
    },
    {
        "title": "Editing & AI Voice",
        "summary": "Rewrite the script, swap voices, and add zooms, crops, and elements.",
        "tags_json": ["editor", "ai"],
        "body_md": (
            "# In the Editor\n\n"
            "- **Script**: click a word to jump the video there; **✨ AI Rewrite** polishes "
            "the whole script (pick a tone), **✍ Generate** writes narration for empty scenes.\n"
            "- **AI Voice**: preview voices and replace your narration; **↻ Refresh voice** "
            "after edits.\n"
            "- **Zoom**: **✨ Suggest zooms with AI**, or drag the focus point yourself.\n"
            "- **Trim / Crop / Elements**: reframe and add text/highlights.\n"
            "- **Timeline**: drag scenes, split, duplicate; **⌘Z** to undo."
        ),
    },
]

def seed_for_user(db: Session, user_id: str) -> dict:
    """Give one user's space its starting content. Called on registration."""
    counts = {"skills": 0, "articles": 0}

    # drop superseded sample skills, then add any canonical ones that are missing
    for old in db.scalars(
        select(Skill).where(Skill.user_id == user_id, Skill.name.in_(_OLD_SAMPLE_NAMES))
    ):
        db.delete(old)
    existing = {s.name for s in db.scalars(select(Skill).where(Skill.user_id == user_id))}
    for s in SAMPLE_SKILLS:
        if s["name"] not in existing:
            db.add(Skill(user_id=user_id, **s))
            counts["skills"] += 1

    has_articles = db.scalar(
        select(func.count(KbArticle.id)).where(KbArticle.user_id == user_id)
    )
    if not has_articles:
        db.add_all([KbArticle(user_id=user_id, **a) for a in SAMPLE_ARTICLES])
        counts["articles"] = len(SAMPLE_ARTICLES)

    db.commit()
    return counts


def seed_all_users() -> dict:
    """Top up every existing account's space. Run with: python -m app.seed"""
    from app.models import User

    init_db()
    db = SessionLocal()
    totals = {"skills": 0, "articles": 0, "users": 0}
    try:
        for user in db.scalars(select(User)):
            counts = seed_for_user(db, user.id)
            totals["skills"] += counts["skills"]
            totals["articles"] += counts["articles"]
            totals["users"] += 1
    finally:
        db.close()
    return totals


if __name__ == "__main__":
    print("seeded:", seed_all_users())
