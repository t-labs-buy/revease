"""Auto Record segmentation: the agent's own decision log -> candidate steps.

Unlike `segment.py` (which *infers* steps from raw clicks + transcript), an Auto
Record run already knows every step's action/target/intent/screen at decision time.
So this is a pure, deterministic projection of the agent log — no guessing:

- keep only successful, graph-worthy actions (drop wait/done/fail and errored tries)
- timing comes from the matching telemetry Event (seq == decision index), which the
  extension measured against the recording clock; fall back to the log's own t_ms
- boundaries mirror `_segment_by_clicks`: step 1 starts at 0 (leading pad), each
  other at its own timestamp, the last runs to the recording end (trailing pad)

Kept as a pure function over plain data so it is exhaustively unit-testable.
"""

from __future__ import annotations

from typing import Any

# Agent action -> Workflow Graph action. Only these become steps; wait/done/fail
# are control flow and never reach the graph.
_ACTION_MAP = {
    "click": "click",
    "input": "input",
    "navigate": "navigation",
    "navigation": "navigation",
    "scroll": "scroll",
    "keydown": "keydown",
    "key": "keydown",
}


def segment_auto(
    agent_log: list[dict[str, Any]],
    events_by_index: dict[int, dict[str, Any]],
    screenshots_by_seq: dict[int, str],
    duration_s: float,
) -> list[dict[str, Any]]:
    """Project the agent log onto ordered candidate steps.

    `events_by_index` maps a decision index -> its telemetry event ({t_ms, bbox,
    selector}); `screenshots_by_seq` maps the same index -> a screenshot storage key.
    """
    kept: list[dict[str, Any]] = []
    for entry in agent_log:
        if not entry.get("ok"):
            continue
        action = _ACTION_MAP.get(str(entry.get("action")))
        if action is None:
            continue
        idx = entry.get("index")
        ev = events_by_index.get(idx, {}) if idx is not None else {}
        t_ms = ev.get("t_ms")
        if t_ms is None:
            t_ms = entry.get("t_ms")
        kept.append(
            {
                "index": idx,
                "action": action,
                "target": entry.get("target") or entry.get("selector") or "element",
                "intent": entry.get("intent"),
                "screen_name": entry.get("screen_name"),
                "selector": entry.get("selector") or ev.get("selector"),
                "bbox": entry.get("bbox") or ev.get("bbox"),
                "plan_item_id": entry.get("plan_item_id"),
                "screenshot": screenshots_by_seq.get(idx) if idx is not None else None,
                "t_ms": float(t_ms) if t_ms is not None else None,
            }
        )

    # Order by measured time when we have it, else by decision order (stable).
    kept.sort(key=lambda s: (s["t_ms"] is None, s["t_ms"] if s["t_ms"] is not None else 0.0))

    steps: list[dict[str, Any]] = []
    n = len(kept)
    for i, s in enumerate(kept):
        t_click = (s["t_ms"] / 1000.0) if s["t_ms"] is not None else 0.0
        t_start = 0.0 if i == 0 else t_click
        if i + 1 < n and kept[i + 1]["t_ms"] is not None:
            t_end = kept[i + 1]["t_ms"] / 1000.0
        else:
            t_end = max(duration_s, t_click)
        steps.append(
            {
                "action": s["action"],
                "target": s["target"],
                "intent": s["intent"],
                "screen_name": s["screen_name"],
                "selector": s["selector"],
                "bbox": s["bbox"],
                "screenshot": s["screenshot"],
                "plan_item_id": s["plan_item_id"],
                "t_start": round(t_start, 3),
                "t_end": round(max(t_end, t_start), 3),
                "narration_span": "",
            }
        )
    return steps
