"""Auto Record — AI-driven browser-tab recording.

The extension records the tab and runs an observe->decide->act loop; this router is
the decision server. `/runs/{id}/step` is a synchronous Claude call (the extension is
blocked on the answer anyway) that returns the single next action. When the run ends,
`/runs/{id}/complete` hands the recorded session to the ordinary understanding
pipeline, which builds the Workflow Graph from the agent's own decision log."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent import decide_next_action
from app.db import get_session
from app.models import AutoRecordRun, CaptureSession, Event, Job, Project
from app.queue import enqueue_understanding
from app.schemas import (
    ActionResult,
    AgentAction,
    AgentStepIn,
    AgentStepOut,
    AutoRecordCreate,
    AutoRecordRunOut,
    JobOut,
    PlanItemOut,
    SessionStatus,
)

router = APIRouter(prefix="/auto-record", tags=["auto-record"])

_LOGGABLE = {"click", "input", "scroll", "navigate", "keydown"}
_TERMINAL = {"ready", "failed", "aborted"}


# --------------------------------------------------------------------------- #
def _get_run_or_404(db: Session, run_id: str) -> AutoRecordRun:
    run = db.get(AutoRecordRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


def _parse_plan(text: str) -> list[dict]:
    """Turn the free-text coverage plan (bullets / numbered / lines) into plan items."""
    items: list[dict] = []
    for line in (text or "").splitlines():
        s = line.strip().lstrip("-*•").strip()
        while s[:1].isdigit():  # strip leading "1." / "2)" numbering
            s = s[1:]
        s = s.lstrip(".) ").strip()
        if s:
            items.append({"id": f"p{len(items) + 1}", "text": s[:300], "status": "pending"})
    if not items and text.strip():
        items = [{"id": "p1", "text": text.strip()[:300], "status": "pending"}]
    return items


def _plan_out(plan: list[dict]) -> list[PlanItemOut]:
    return [PlanItemOut(id=it["id"], text=it["text"], status=it.get("status", "pending")) for it in plan]


def _action_from_entry(entry: dict) -> AgentAction:
    return AgentAction(
        index=entry["index"],
        action=entry.get("action", "wait"),
        ref=entry.get("ref"),
        text=entry.get("text"),
        url=entry.get("url"),
        key=entry.get("key"),
        wait_ms=entry.get("wait_ms"),
        scroll_to=entry.get("scroll_to"),
        clear=bool(entry.get("clear")),
        press_enter=bool(entry.get("press_enter")),
        target=entry.get("target"),
        intent=entry.get("intent"),
        screen_name=entry.get("screen_name"),
        plan_item_id=entry.get("plan_item_id"),
    )


def _step_out(run: AutoRecordRun, entry: dict, plan: list[dict]) -> AgentStepOut:
    done = bool(entry.get("done"))
    return AgentStepOut(
        action=_action_from_entry(entry),
        done=done,
        progress_note=entry.get("progress_note"),
        plan=_plan_out(plan),
        step_count=run.step_count,
    )


def _apply_results(log: list[dict], results: list[ActionResult]) -> None:
    by_index = {e["index"]: e for e in log}
    for r in results:
        e = by_index.get(r.index)
        if e is None:
            continue
        e["ok"] = r.ok
        e["error"] = r.error
        if r.selector is not None:
            e["selector"] = r.selector
        if r.bbox is not None:
            e["bbox"] = r.bbox
        if r.t_ms is not None:
            e["t_ms"] = r.t_ms


# --------------------------------------------------------------------------- #
@router.post("/runs", response_model=AutoRecordRunOut, status_code=status.HTTP_201_CREATED)
def create_run(payload: AutoRecordCreate, db: Session = Depends(get_session)) -> AutoRecordRunOut:
    if db.get(Project, payload.project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    plan = _parse_plan(payload.coverage_plan)
    if not plan:
        raise HTTPException(status_code=400, detail="coverage plan is empty")

    sess = CaptureSession(
        project_id=payload.project_id,
        source_type="auto",
        telemetry="absent",
        status="created",
        viewport_json=payload.viewport.model_dump() if payload.viewport else None,
    )
    db.add(sess)
    db.flush()
    run = AutoRecordRun(
        project_id=payload.project_id,
        session_id=sess.id,
        status="created",
        start_url=payload.start_url,
        coverage_plan_json=plan,
        transcript_text=payload.transcript or "",
        agent_log_json=[],
        max_steps=payload.max_steps,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return _run_out(db, run)


@router.post("/runs/{run_id}/step", response_model=AgentStepOut)
def agent_step(
    run_id: str, payload: AgentStepIn, db: Session = Depends(get_session)
) -> AgentStepOut:
    run = _get_run_or_404(db, run_id)
    if run.status in _TERMINAL:
        raise HTTPException(status_code=409, detail=f"run is {run.status}")

    log = list(run.agent_log_json or [])
    plan = list(run.coverage_plan_json or [])

    # Idempotent replay: the extension retried a step it already received.
    if payload.expected_index == run.step_count - 1 and log:
        return _step_out(run, log[-1], plan)
    if payload.expected_index != run.step_count:
        raise HTTPException(
            status_code=409,
            detail=f"expected_index {payload.expected_index} != step_count {run.step_count}",
        )

    _apply_results(log, payload.results)
    run.status = "driving"

    # Server-enforced cap: end deterministically even if the model never says done.
    if run.step_count >= run.max_steps:
        entry = {"index": run.step_count, "action": "done", "done": True,
                 "progress_note": "Reached the step limit."}
        log.append(entry)
        run.step_count += 1
        run.agent_log_json = log
        db.commit()
        return _step_out(run, entry, plan)

    obs = payload.observation.model_dump()
    try:
        decision = decide_next_action(
            coverage_plan=plan,
            transcript=run.transcript_text,
            agent_log=log,
            observation=obs,
        )
    except Exception as e:
        run.error_json = {"error": str(e)}
        run.agent_log_json = log
        db.commit()
        raise HTTPException(status_code=502, detail=f"agent decision failed: {e}") from e

    action_name = decision.get("action") or "wait"
    done = action_name in ("done", "fail")

    # Plan-state bookkeeping (server is source of truth).
    pid = decision.get("plan_item_id")
    if pid:
        for it in plan:
            if it["id"] == pid:
                it["status"] = "done" if decision.get("plan_item_completed") else "active"
        run.current_plan_item = pid
    if action_name == "done":
        for it in plan:
            it["status"] = "done"

    entry = {
        "index": run.step_count,
        "action": action_name,
        "ref": decision.get("ref"),
        "text": decision.get("text"),
        "url": decision.get("url"),
        "key": decision.get("key"),
        "wait_ms": decision.get("wait_ms"),
        "scroll_to": decision.get("scroll_to"),
        "clear": bool(decision.get("clear")),
        "press_enter": bool(decision.get("press_enter")),
        "target": decision.get("target"),
        "intent": decision.get("intent"),
        "screen_name": decision.get("screen_name"),
        "plan_item_id": pid,
        "progress_note": decision.get("progress_note"),
        "done": done,
        # ok/selector/bbox/t_ms filled from the extension's result on the next step
        "ok": None if action_name in _LOGGABLE else True,
    }
    log.append(entry)
    run.step_count += 1
    if action_name == "fail":
        run.error_json = {"error": decision.get("progress_note") or "agent gave up"}
    run.coverage_plan_json = plan
    run.agent_log_json = log
    db.commit()
    return _step_out(run, entry, plan)


class RunComplete(BaseModel):
    status: str = "completed"  # completed | aborted | failed
    duration_ms: int | None = None


@router.post("/runs/{run_id}/complete", response_model=AutoRecordRunOut)
def complete_run(
    run_id: str, payload: RunComplete, db: Session = Depends(get_session)
) -> AutoRecordRunOut:
    """Finalize a run: mark the session captured and kick off the understanding
    pipeline (which builds the graph from the agent log). Reuses the same enqueue
    path as manual sessions so nothing downstream is Auto-Record-specific."""
    run = _get_run_or_404(db, run_id)
    sess = db.get(CaptureSession, run.session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")

    if payload.status != "completed":
        run.status = "aborted" if payload.status == "aborted" else "failed"
        sess.status = "aborted"
        db.commit()
        return _run_out(db, run)

    event_count = db.scalar(
        select(func.count()).select_from(Event).where(Event.session_id == sess.id)
    )
    sess.telemetry = "present" if (event_count or 0) > 0 else "absent"
    sess.status = "captured"
    if payload.duration_ms is not None:
        sess.duration_ms = payload.duration_ms
    run.status = "capture_done"
    db.commit()
    enqueue_understanding(sess.id)
    db.refresh(run)
    return _run_out(db, run)


@router.post("/runs/{run_id}/abort", response_model=AutoRecordRunOut)
def abort_run(run_id: str, db: Session = Depends(get_session)) -> AutoRecordRunOut:
    run = _get_run_or_404(db, run_id)
    if run.status not in _TERMINAL:
        run.status = "aborted"
        sess = db.get(CaptureSession, run.session_id)
        if sess is not None and sess.status not in ("ready",):
            sess.status = "aborted"
        db.commit()
        db.refresh(run)
    return _run_out(db, run)


@router.get("/runs", response_model=list[AutoRecordRunOut])
def list_runs(
    project_id: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_session),
) -> list[AutoRecordRunOut]:
    q = select(AutoRecordRun).order_by(AutoRecordRun.created_at.desc()).limit(limit)
    if project_id:
        q = q.where(AutoRecordRun.project_id == project_id)
    return [_run_out(db, r) for r in db.scalars(q)]


@router.get("/runs/{run_id}", response_model=AutoRecordRunOut)
def get_run(run_id: str, db: Session = Depends(get_session)) -> AutoRecordRunOut:
    return _run_out(db, _get_run_or_404(db, run_id))


def _run_out(db: Session, run: AutoRecordRun) -> AutoRecordRunOut:
    session_status = None
    if run.status in ("processing", "ready"):
        sess = db.get(CaptureSession, run.session_id)
        if sess is not None:
            latest = db.scalar(select(func.max(Job.version)).where(Job.session_id == sess.id))
            jobs = db.scalars(
                select(Job).where(Job.session_id == sess.id).order_by(Job.version, Job.updated_at)
            )
            session_status = SessionStatus(
                session_id=sess.id,
                status=sess.status,
                latest_version=latest,
                jobs=[JobOut.model_validate(j) for j in jobs if j.version == (latest or 0)],
            )
    return AutoRecordRunOut(
        run_id=run.id,
        session_id=run.session_id,
        project_id=run.project_id,
        status=run.status,
        plan=_plan_out(run.coverage_plan_json or []),
        current_plan_item=run.current_plan_item,
        step_count=run.step_count,
        max_steps=run.max_steps,
        error=run.error_json,
        session_status=session_status,
    )
