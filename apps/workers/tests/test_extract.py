from refract_workflow_graph import validate
from worker.pipeline.extract import build_graph


def _candidates(n=3):
    return [
        {
            "action": "click",
            "target": f"Button {i}",
            "selector": f"#b{i}",
            "bbox": [i, i, 8, 8],
            "screenshot": f"shot{i}.png",
            "t_start": float(i),
            "t_end": float(i + 1),
            "narration_span": "",
        }
        for i in range(n)
    ]


def test_build_graph_is_schema_valid_and_linear():
    g = build_graph(_candidates(3), workflow_id="wf_test", title="T", version=1)
    assert validate(g).valid
    assert [s["id"] for s in g["steps"]] == ["s1", "s2", "s3"]
    # every step has action + target (extraction contract)
    assert all(s["action"] and s["target"] for s in g["steps"])
    # linear edges
    assert g["edges"] == [
        {"from": "s1", "to": "s2", "condition": None},
        {"from": "s2", "to": "s3", "condition": None},
    ]


def test_narration_is_verbatim_transcript_span():
    # Silent step -> empty narration (never an invented sentence)…
    g = build_graph(_candidates(1), workflow_id="wf_test", title="T", version=1)
    assert g["steps"][0]["narration"] == ""
    # …and a spoken span is carried through word-for-word.
    cands = _candidates(1)
    cands[0]["narration_span"] = "now we open the settings page"
    g = build_graph(cands, workflow_id="wf_test", title="T", version=1)
    assert g["steps"][0]["narration"] == "now we open the settings page"


def test_single_step_no_edges():
    g = build_graph(_candidates(1), workflow_id="wf_test", title="T", version=2)
    assert validate(g).valid and g["edges"] == []
