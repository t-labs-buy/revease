"""Step-by-step doc (SOP) generation from a Workflow Graph, plus Markdown and PDF
export. Deterministic — derived directly from the graph the pipeline already
produced (title, per-step action/target/narration, best keyframe)."""

from __future__ import annotations

import re
from typing import Any

from app.storage import store


def build_document(graph_json: dict[str, Any]) -> dict[str, Any]:
    steps = graph_json.get("steps", [])
    out_steps = []
    for i, s in enumerate(steps, start=1):
        action = (s.get("action") or "custom").capitalize()
        target = s.get("target") or "the element"
        title = f"{action} {target}".strip()
        body = (s.get("narration") or s.get("intent") or title).strip()
        out_steps.append(
            {
                "n": i,
                "title": title[:160],
                "body": body,
                "screenshot": s.get("screenshot"),
            }
        )
    title = graph_json.get("title") or "Workflow"
    return {
        "title": title,
        "summary": f"A step-by-step guide with {len(out_steps)} step"
        f"{'' if len(out_steps) == 1 else 's'}.",
        "graph_version": graph_json.get("version", 1),
        "steps": out_steps,
    }


def render_markdown(doc: dict[str, Any], media_base: str = "") -> str:
    lines = [f"# {doc['title']}", "", doc.get("summary", ""), ""]
    for s in doc["steps"]:
        lines.append(f"## {s['n']}. {s['title']}")
        lines.append("")
        if s.get("body"):
            lines.append(s["body"])
            lines.append("")
        if s.get("screenshot"):
            url = f"{media_base}/media/{s['screenshot']}" if media_base else s["screenshot"]
            lines.append(f"![Step {s['n']}]({url})")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _latin(text: str) -> str:
    """fpdf core fonts are latin-1; map common unicode then drop the rest."""
    text = (text or "").replace("→", "->").replace("—", "-").replace("’", "'").replace("“", '"').replace("”", '"')
    return text.encode("latin-1", "replace").decode("latin-1")


def render_pdf(doc: dict[str, Any]) -> bytes:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    pdf = FPDF(format="A4")
    pdf.set_margins(16, 16, 16)
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()

    def cell(h: float, text: str) -> None:
        # new_x=LMARGIN keeps the cursor at the left margin (fpdf2 defaults to RIGHT).
        pdf.multi_cell(0, h, _latin(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", "B", 20)
    cell(10, doc["title"])
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(110, 110, 110)
    cell(7, doc.get("summary", ""))
    pdf.set_text_color(20, 20, 20)
    pdf.ln(4)

    usable_w = pdf.epw
    for s in doc["steps"]:
        pdf.set_font("Helvetica", "B", 13)
        cell(8, f"{s['n']}. {s['title']}")
        pdf.set_font("Helvetica", "", 11)
        if s.get("body"):
            cell(6, s["body"])
        if s.get("screenshot"):
            try:
                path = store.local_path(s["screenshot"])
                if path.exists():
                    pdf.ln(1)
                    pdf.image(str(path), w=min(usable_w, 150))
            except Exception:
                pass
        pdf.ln(5)

    out = pdf.output()  # fpdf2 returns a bytearray
    return bytes(out)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "document").lower()).strip("-") or "document"
