from app.diff import diff_graphs, migrate_edit_spec
from app.editspec import build_edit_spec


def _g(version, steps):
    return {
        "workflow_id": "wf",
        "version": version,
        "title": "T",
        "steps": steps,
        "edges": [],
    }


def _s(sid, action, target, narration=""):
    return {"id": sid, "action": action, "target": target, "narration": narration, "bbox": None}


def test_diff_added_changed_unchanged_removed():
    old = _g(1, [
        _s("s1", "click", "Settings", "Open settings."),
        _s("s2", "click", "API Keys", "Open API keys."),
        _s("s3", "click", "Delete", "Delete it."),
    ])
    new = _g(2, [
        _s("a1", "click", "Settings", "Open settings."),          # unchanged
        _s("a2", "click", "API Keys", "Open the API keys page."),  # changed narration
        _s("a3", "click", "Create key", "Make a new key."),        # added
    ])
    d = diff_graphs(old, new)
    by_id = {s["id"]: s for s in d["steps"]}
    assert by_id["a1"]["status"] == "unchanged" and by_id["a1"]["old_id"] == "s1"
    assert by_id["a2"]["status"] == "changed"
    assert by_id["a3"]["status"] == "added"
    assert d["summary"] == {"added": 1, "changed": 1, "unchanged": 1, "removed": 1}
    assert d["removed"][0]["target"] == "Delete"


def test_migrate_carries_edits_and_marks_dirty():
    old_g = _g(1, [_s("s1", "click", "Settings", "Open settings."),
                   _s("s2", "click", "API Keys", "Open API keys.")])
    old_spec = build_edit_spec(old_g, {"w": 1280, "h": 720})
    # user edits step 1's script and disables its zoom
    old_spec["segments"][0]["words"] = ["My", "custom", "narration."]
    old_spec["segments"][0]["removed"] = [1]
    old_spec["segments"][0]["zoom"]["enabled"] = False
    old_spec["voice"]["speed"] = 1.25

    new_g = _g(2, [_s("s1", "click", "Settings", "Open settings."),           # unchanged
                   _s("s2", "click", "API Keys", "Open the API keys page."),  # changed
                   _s("s3", "click", "Create key", "New key.")])              # added

    migrated = migrate_edit_spec(old_spec, old_g, new_g, {"w": 1280, "h": 720})
    segs = {s["step_id"]: s for s in migrated["segments"]}
    # unchanged step keeps the user's edits and is not dirty
    assert segs["s1"]["words"] == ["My", "custom", "narration."]
    assert segs["s1"]["removed"] == [1]
    assert segs["s1"]["zoom"]["enabled"] is False
    assert segs["s1"]["dirty"] is False
    # changed + added are dirty (will regenerate)
    assert segs["s2"]["dirty"] is True
    assert segs["s3"]["dirty"] is True
    # project-level settings carried over
    assert migrated["voice"]["speed"] == 1.25
