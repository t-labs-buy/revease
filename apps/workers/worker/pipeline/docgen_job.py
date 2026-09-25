"""Orchestrates documentation generation for a project: write the text (LLM or
fallback, via app.docwriter), grab + annotate one snapshot per step, persist a
DocV2 on the Document row. Also the single-step re-grab.

Idempotency: (project_id, doc_version) is the key. The API bumps the row's
doc_version on every request; a task carrying an older version is a stale
redelivery and drops itself. The text is written before the frames so a broken
ffmpeg still yields a usable document (snapshots null), and one bad frame only
nulls that step.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.config import get_settings
from app.db import SessionLocal
from app.docwriter import effective_narrations, write_document
from app.models import (
    CaptureSession,
    Document,
    Event,
    Job,
    MediaAsset,
    Project,
    Skill,
    Transcript,
    VideoProject,
    WorkflowGraphRow,
)
from app.schemas import DocV2
from app.storage import store
from worker.pipeline import docshots
from worker.pipeline.progress import Heartbeat, Reporter
from worker.pipeline.render import _click_points, _find_source_video
from worker.pipeline.run import _load_keyframes
from worker.pipeline.tts import _probe_duration_ms

log = logging.getLogger("refract.pipeline.docgen_job")


def _latest_graph(db, project_id: str) -> WorkflowGraphRow | None:
    return db.scalar(
        select(WorkflowGraphRow)
        .where(WorkflowGraphRow.project_id == project_id)
        .order_by(WorkflowGraphRow.version.desc())
    )


def _source_for_graph(db, project_id: str, graph_version: int):
    """(video_path, session) — prefer the session whose pipeline run produced
    this graph version (multi-capture projects), else the first with a video."""
    preferred = db.scalar(
        select(Job.session_id)
        .join(CaptureSession, CaptureSession.id == Job.session_id)
        .where(CaptureSession.project_id == project_id, Job.stage == "extract", Job.version == graph_version)
    )
    if preferred:
        asset = db.scalar(
            select(MediaAsset).where(MediaAsset.session_id == preferred, MediaAsset.kind == "raw_video")
        )
        path = store.fetch(asset.storage_key) if asset else None
        if path is not None:
            return path, db.get(CaptureSession, preferred)
    video, sid = _find_source_video(db, project_id)
    return video, (db.get(CaptureSession, sid) if sid else None)


def _transcript_text(db, project_id: str) -> str:
    rows = db.execute(
        select(Transcript.text)
        .join(CaptureSession, CaptureSession.id == Transcript.session_id)
        .where(CaptureSession.project_id == project_id)
        .order_by(CaptureSession.created_at)
    ).all()
    return "\n".join((r[0] or "").strip() for r in rows if r[0]).strip()


def _event_bboxes(db, session_id: str | None) -> list[tuple[int, list[float]]]:
    """[(t_ms, bbox)] for click events — a fallback when a graph step lost its bbox."""
    if not session_id:
        return []
    out = []
    for e in db.scalars(select(Event).where(Event.session_id == session_id, Event.type == "click")):
        if isinstance(e.bbox_json, (list, tuple)) and len(e.bbox_json) == 4:
            out.append((int(e.t_ms), list(e.bbox_json)))
    return sorted(out)


def _bbox_for(step: dict[str, Any], events: list[tuple[int, list[float]]]) -> Any:
    if step.get("bbox"):
        return step["bbox"]
    t0 = float(step.get("t_start") or 0.0)
    t1 = float(step.get("t_end") or t0)
    for t_ms, bbox in events:
        if t0 - 0.25 <= t_ms / 1000.0 <= t1:
            return bbox
    return None


def _skill_settings(db, project: Project, skill_id: str | None) -> dict[str, Any] | None:
    if not skill_id:
        return None
    skill = db.get(Skill, skill_id)
    if skill is None or skill.target != "doc" or (project.user_id and skill.user_id != project.user_id):
        return None
    return skill.settings_json or {}


def _cleanup_old_docshots(db, session_id: str, keep: set[str], doc_version: int) -> None:
    """Best effort: drop docshots from earlier generations that the new doc no
    longer references (the files are small, but they add up per regenerate)."""
    for asset in list(
        db.scalars(select(MediaAsset).where(MediaAsset.session_id == session_id, MediaAsset.kind == "docshot"))
    ):
        meta = asset.meta_json or {}
        if meta.get("doc_version", 0) >= doc_version or asset.storage_key in keep:
            continue
        for key in (asset.storage_key, meta.get("raw_key")):
            try:
                if key:
                    store.delete(key)
            except Exception:  # pragma: no cover
                pass
        db.delete(asset)


def run_document_generate(
    project_id: str, doc_version: int, skill_id: str | None = None, instruction: str | None = None
) -> dict:
    db = SessionLocal()
    try:
        row = db.scalar(select(Document).where(Document.project_id == project_id))
        if row is None:
            log.warning("document for project %s not found; skipping", project_id)
            return {"project_id": project_id, "skipped": "not found"}
        if (row.doc_version or 0) != doc_version:
            log.info("document %s: stale task (v%s, row is v%s); skipping", row.id, doc_version, row.doc_version)
            return {"project_id": project_id, "skipped": "stale"}
        if row.status == "ready":
            return {"project_id": project_id, "skipped": "already ready"}
        row.status = "running"
        row.progress = 0.02
        row.message = "Reading the recording and transcript…"
        db.commit()
        report = Reporter(Document, row.id)
        heartbeat = Heartbeat(Document, row.id).__enter__()

        try:
            graph = _latest_graph(db, project_id)
            if graph is None:
                raise RuntimeError("no workflow graph for this project")
            project = db.get(Project, project_id)
            settings = get_settings()

            video, sess = _source_for_graph(db, project_id, graph.version)
            session_id = sess.id if sess else None
            viewport = (sess.viewport_json if sess else None) or None
            duration_s = 0.0
            if video is not None:
                duration_s = _probe_duration_ms(video) / 1000.0
            if not duration_s and sess and sess.duration_ms:
                duration_s = sess.duration_ms / 1000.0

            vp = db.scalar(select(VideoProject).where(VideoProject.project_id == project_id))
            edit_spec = vp.edit_spec_json if vp and vp.graph_version == graph.version else None
            narrations = effective_narrations(graph.graph_json, edit_spec)
            all_steps = [dict(s, narration=narrations.get(s["id"], s.get("narration") or ""))
                         for s in graph.graph_json.get("steps", [])]

            skill_settings = _skill_settings(db, project, skill_id)
            report(0.1, f"Writing the guide for {len(all_steps)} steps…")
            doc = write_document(
                project_title=(project.name if project else None) or graph.graph_json.get("title") or "Workflow",
                transcript_text=_transcript_text(db, project_id),
                steps=all_steps,
                skill_settings=skill_settings,
                instruction=instruction,
                graph_version=graph.version,
                skill_id=skill_id,
            )

            # ---- snapshots ----
            want_snapshots = doc["meta"].get("snapshots", True) is not False
            clicks = _click_points(db, session_id)
            events = _event_bboxes(db, session_id)
            keyframes = _load_keyframes(db, session_id) if session_id else []
            by_id = {s["id"]: s for s in all_steps}
            annotate_ok = annotate_policy = docshots.annotate_policy(sess.source_type if sess else None)
            keep: set[str] = set()
            if want_snapshots and session_id:
                n_steps = max(1, len(doc["steps"]))
                for si, step in enumerate(doc["steps"]):
                    report(0.45 + 0.5 * si / n_steps, f"Capturing snapshot {si + 1} of {len(doc['steps'])}…")
                    g = by_id.get(step["id"])
                    if g is None:  # user-added ids never come out of the writer, but be safe
                        continue
                    try:
                        t, reason = docshots.pick_snapshot_time(
                            g, clicks, duration_s, click_offset_s=settings.doc_snapshot_click_offset_ms / 1000.0
                        )
                        bbox_norm = (
                            docshots.bbox_to_frame_norm(_bbox_for(g, events), viewport) if annotate_ok else None
                        )
                        snap = docshots.make_snapshot(
                            db, session_id, video, step["id"], t, bbox_norm,
                            keyframes=keyframes, graph_screenshot=g.get("screenshot"),
                            doc_version=doc_version, max_w=settings.doc_snapshot_max_width,
                        )
                        step["snapshot"] = snap
                        if snap:
                            keep.update(k for k in (snap["key"], snap["raw_key"]) if k)
                        log.info("docshot %s: t=%.2f (%s) annotated=%s", step["id"], t, reason, bool(bbox_norm))
                    except Exception as e:  # one bad frame must not kill the document
                        log.warning("docshot for step %s failed: %s", step["id"], e)
                        step["snapshot"] = None
                _cleanup_old_docshots(db, session_id, keep, doc_version)
            else:
                for step in doc["steps"]:
                    step["snapshot"] = None

            doc = DocV2.model_validate(doc).model_dump()
            row.doc_json = doc
            row.graph_version = graph.version
            row.status = "ready"
            row.error_json = None
            row.progress = 1.0
            row.message = f"Ready · {len(doc['steps'])} steps"
            flag_modified(row, "doc_json")
            db.commit()
            heartbeat.__exit__(None, None, None)
            return {
                "project_id": project_id,
                "doc_version": doc_version,
                "steps": len(doc["steps"]),
                "snapshots": sum(1 for s in doc["steps"] if s.get("snapshot")),
                "writer": doc["meta"].get("writer"),
                "annotated": annotate_policy,
            }
        except Exception as e:
            heartbeat.__exit__(None, None, None)
            db.rollback()
            row = db.scalar(select(Document).where(Document.project_id == project_id))
            if row is not None and (row.doc_version or 0) == doc_version:
                row.message = "Generation failed"
                row.status = "error"
                row.error_json = {"error": str(e)[:2000]}
                db.commit()
            log.exception("document generation failed for project %s", project_id)
            raise
    finally:
        db.close()


def run_document_snapshot(project_id: str, step_id: str, t_seconds: float) -> dict:
    """Re-grab one step's snapshot at `t_seconds`. Only that step's `snapshot`
    is rewritten, after a fresh read, so concurrent text edits survive."""
    db = SessionLocal()
    try:
        row = db.scalar(select(Document).where(Document.project_id == project_id))
        if row is None or not row.doc_json:
            return {"project_id": project_id, "skipped": "no document"}
        graph = _latest_graph(db, project_id)
        graph_json = graph.graph_json if graph else {}
        video, sess = _source_for_graph(db, project_id, row.graph_version)
        if sess is None:
            return {"project_id": project_id, "skipped": "no session"}
        settings = get_settings()

        duration_s = (_probe_duration_ms(video) / 1000.0) if video is not None else 0.0
        if not duration_s and sess.duration_ms:
            duration_s = sess.duration_ms / 1000.0
        t = max(0.0, float(t_seconds))
        if duration_s:
            t = min(t, max(0.0, duration_s - 0.05))
        t = round(t, 3)

        steps = row.doc_json.get("steps") or []
        step = next((s for s in steps if s.get("id") == step_id), None)
        if step is None:
            return {"project_id": project_id, "skipped": "no such step"}

        gid = (step.get("source") or {}).get("graph_step_id")
        g = next((s for s in graph_json.get("steps", []) if s["id"] == gid), None) if gid else None
        bbox_norm = None
        if g is not None and docshots.annotate_policy(sess.source_type):
            bbox_norm = docshots.bbox_to_frame_norm(_bbox_for(g, _event_bboxes(db, sess.id)), sess.viewport_json)

        snap = docshots.make_snapshot(
            db, sess.id, video, step_id, t, bbox_norm,
            keyframes=_load_keyframes(db, sess.id), graph_screenshot=(g or {}).get("screenshot"),
            doc_version=row.doc_version or 0, max_w=settings.doc_snapshot_max_width,
        )

        # re-read: the user may have saved text while the frame was being grabbed
        db.refresh(row)
        steps = row.doc_json.get("steps") or []
        step = next((s for s in steps if s.get("id") == step_id), None)
        if step is not None:
            if snap is None:
                prev = dict(step.get("snapshot") or {})
                prev["pending"] = False
                step["snapshot"] = prev if prev.get("key") else None
            else:
                step["snapshot"] = snap
            flag_modified(row, "doc_json")
            db.commit()
        return {"project_id": project_id, "step_id": step_id, "t": t, "ok": snap is not None}
    finally:
        db.close()
