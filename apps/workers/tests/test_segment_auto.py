from refract_workflow_graph import validate

from worker.pipeline.extract import build_graph_auto
from worker.pipeline.segment_auto import segment_auto


def _log(*entries):
    """entries: (index, action, ok, **overrides)."""
    out = []
    for index, action, ok, *rest in entries:
        overrides = rest[0] if rest else {}
        out.append(
            {
                "index": index,
                "action": action,
                "ok": ok,
                "target": f"Item {index}",
                "intent": "do a thing",
                "screen_name": "Screen",
                "selector": f"#b{index}",
                "bbox": [index, index, 8, 8],
                "plan_item_id": "p1",
                **overrides,
            }
        )
    return out


def _events(*pairs):
    return {idx: {"t_ms": t, "bbox": [1, 1, 2, 2], "selector": f"#b{idx}"} for idx, t in pairs}


def test_only_successful_loggable_actions_become_steps():
    log = _log(
        (0, "navigate", True),
        (1, "click", True),
        (2, "wait", True),  # control flow -> dropped
        (3, "input", True),
        (4, "done", True),  # control flow -> dropped
    )
    events = _events((0, 0), (1, 2000), (3, 4000))
    steps = segment_auto(log, events, {}, duration_s=6.0)
    assert [s["action"] for s in steps] == ["navigation", "click", "input"]


def test_errored_attempts_are_dropped():
    log = _log((0, "click", False), (1, "click", True))
    steps = segment_auto(log, _events((1, 1000)), {}, duration_s=3.0)
    assert len(steps) == 1 and steps[0]["selector"] == "#b1"


def test_boundaries_pad_first_and_last():
    log = _log((0, "click", True), (1, "click", True), (2, "click", True))
    events = _events((0, 1000), (1, 3000), (2, 5000))
    steps = segment_auto(log, events, {}, duration_s=7.0)
    assert steps[0]["t_start"] == 0.0 and steps[0]["t_end"] == 3.0  # first pads to 0
    assert steps[1]["t_start"] == 3.0 and steps[1]["t_end"] == 5.0
    assert steps[2]["t_start"] == 5.0 and steps[2]["t_end"] == 7.0  # last runs to end


def test_screenshot_matched_by_index():
    log = _log((0, "click", True))
    steps = segment_auto(log, _events((0, 500)), {0: "shots/s0.jpg"}, duration_s=2.0)
    assert steps[0]["screenshot"] == "shots/s0.jpg"


def test_build_graph_auto_is_schema_valid_and_no_llm():
    log = _log((0, "click", True), (1, "input", True))
    events = _events((0, 500), (1, 1500))
    steps = segment_auto(log, events, {0: "a.jpg", 1: "b.jpg"}, duration_s=3.0)
    g = build_graph_auto(steps, workflow_id="wf_auto", title="Demo", version=1)
    assert validate(g).valid
    assert [s["id"] for s in g["steps"]] == ["s1", "s2"]
    # grounded steps (selector + screenshot) are trusted, not needs_review
    assert all(s["review_status"] == "auto" and s["confidence"] == 0.95 for s in g["steps"])
    # intent/screen carried straight through from the agent log (no inference)
    assert g["steps"][0]["intent"] == "do a thing"


def test_build_graph_auto_flags_thin_steps_for_review():
    log = _log((0, "scroll", True, {"selector": None}))
    steps = segment_auto(log, _events((0, 0)), {}, duration_s=1.0)
    g = build_graph_auto(steps, workflow_id="wf_auto", title="Demo", version=1)
    assert g["steps"][0]["review_status"] == "needs_review"
