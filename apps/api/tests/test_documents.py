from fastapi.testclient import TestClient

from app.docgen import build_document, render_markdown, render_pdf
from app.main import app

client = TestClient(app)

GRAPH = {
    "workflow_id": "wf_d",
    "version": 1,
    "title": "Create an API key",
    "steps": [
        {"id": "s1", "action": "click", "target": "Settings → API Keys",
         "narration": "Open the API Keys page.", "screenshot": None},
        {"id": "s2", "action": "click", "target": "Create key",
         "narration": "Click Create key.", "screenshot": None},
    ],
    "edges": [{"from": "s1", "to": "s2", "condition": None}],
}


def test_build_document_shape():
    doc = build_document(GRAPH)
    assert doc["title"] == "Create an API key"
    assert len(doc["steps"]) == 2
    assert doc["steps"][0]["n"] == 1
    assert "Open the API Keys page." in doc["steps"][0]["body"]


def test_markdown_render():
    md = render_markdown(build_document(GRAPH), media_base="http://x")
    assert md.startswith("# Create an API key")
    assert "## 1. Click Settings" in md


def test_pdf_render_bytes():
    pdf = render_pdf(build_document(GRAPH))
    assert pdf[:4] == b"%PDF"  # valid PDF header
    assert len(pdf) > 500


def _project_with_graph() -> str:
    pid = client.post("/projects", json={"name": "doc proj"}).json()["id"]
    # seed a graph directly via the DB layer
    from app.db import SessionLocal
    from app.models import WorkflowGraphRow

    db = SessionLocal()
    db.add(WorkflowGraphRow(project_id=pid, version=1, graph_json=GRAPH))
    db.commit()
    db.close()
    return pid


def test_document_endpoints_and_exports():
    pid = _project_with_graph()
    r = client.get(f"/projects/{pid}/document")
    assert r.status_code == 200 and len(r.json()["doc"]["steps"]) == 2

    md = client.get(f"/projects/{pid}/document/export", params={"format": "md"})
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert md.content.startswith(b"# Create an API key")

    pdf = client.get(f"/projects/{pid}/document/export", params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:4] == b"%PDF"


def test_document_404_without_graph():
    pid = client.post("/projects", json={"name": "empty"}).json()["id"]
    assert client.get(f"/projects/{pid}/document").status_code == 404
