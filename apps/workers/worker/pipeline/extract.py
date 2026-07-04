"""Claude workflow extraction as explicit understand -> validate -> compose nodes
(the LangGraph shape from master §2; kept as plain functions in V1 so it runs and
tests offline). Output validates against the shared Workflow Graph schema — the
single source of truth — before it is ever persisted."""

from __future__ import annotations

import logging
from typing import Any

from refract_workflow_graph import assert_valid, validate

from worker.pipeline.providers import label_steps

log = logging.getLogger("refract.pipeline.extract")


def _clean_bbox(bbox: Any) -> list[float] | None:
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            return [float(x) for x in bbox]
        except (TypeError, ValueError):
            return None
    return None


def build_graph(
    candidate_steps: list[dict[str, Any]],
    *,
    workflow_id: str,
    title: str,
    version: int,
) -> dict[str, Any]:
    # understand: LLM (or deterministic fallback) labels + narrates each step.
    labeled = label_steps(
        [
            {
                "action": s.get("action", "custom"),
                "target": s.get("target"),
                "selector": s.get("selector"),
                "screen_name": None,
                "narration_span": s.get("narration_span"),
            }
            for s in candidate_steps
        ]
    )

    # compose: assemble IR steps (never renumber — ids are s1..sn in timeline order).
    steps: list[dict[str, Any]] = []
    for i, (cand, lab) in enumerate(zip(candidate_steps, labeled), start=1):
        confidence = 0.9 if (lab.get("narration") and cand.get("target")) else 0.6
        steps.append(
            {
                "id": f"s{i}",
                "action": lab.get("action") or cand.get("action") or "custom",
                "target": (lab.get("target") or cand.get("target") or "element")[:200],
                "intent": lab.get("intent"),
                "screen_name": lab.get("screen_name"),
                "selector": cand.get("selector"),
                "screenshot": cand.get("screenshot"),
                "bbox": _clean_bbox(cand.get("bbox")),
                "narration": lab.get("narration") or cand.get("narration_span") or "",
                "t_start": cand.get("t_start"),
                "t_end": cand.get("t_end"),
                "confidence": confidence,
                "review_status": "auto" if confidence >= 0.8 else "needs_review",
            }
        )

    edges = [{"from": f"s{i}", "to": f"s{i + 1}", "condition": None} for i in range(1, len(steps))]

    graph: dict[str, Any] = {
        "workflow_id": workflow_id,
        "version": version,
        "title": title,
        "steps": steps,
        "edges": edges,
    }

    # validate: fail loud with the offending detail rather than persisting junk.
    result = validate(graph)
    if not result.valid:
        log.error("composed graph failed validation: %s", result.errors)
        raise ValueError(f"graph validation failed: {result.errors[:5]}")
    assert_valid(graph)
    return graph
