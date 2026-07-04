"""Seed sample data so Skills / Knowledge Base / Library have content to explore.
Idempotent: only inserts when a table is empty. Run with: python -m app.seed"""

from __future__ import annotations

from sqlalchemy import func, select

from app.db import SessionLocal, init_db
from app.models import KbArticle, Project, Skill

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

SAMPLE_PROJECTS = ["Product Onboarding Walkthrough", "TMS Inbound Vendors Demo"]


def seed_samples() -> dict:
    init_db()
    db = SessionLocal()
    counts = {"skills": 0, "articles": 0, "projects": 0}
    try:
        # drop superseded sample skills, then add any canonical ones that are missing
        for old in db.scalars(select(Skill).where(Skill.name.in_(_OLD_SAMPLE_NAMES))):
            db.delete(old)
        existing = {s.name for s in db.scalars(select(Skill))}
        for s in SAMPLE_SKILLS:
            if s["name"] not in existing:
                db.add(Skill(**s))
                counts["skills"] += 1
        if db.scalar(select(func.count(KbArticle.id))) == 0:
            db.add_all([KbArticle(**a) for a in SAMPLE_ARTICLES])
            counts["articles"] = len(SAMPLE_ARTICLES)
        if db.scalar(select(func.count(Project.id))) == 0:
            db.add_all([Project(name=n) for n in SAMPLE_PROJECTS])
            counts["projects"] = len(SAMPLE_PROJECTS)
        db.commit()
    finally:
        db.close()
    return counts


if __name__ == "__main__":
    print("seeded:", seed_samples())
