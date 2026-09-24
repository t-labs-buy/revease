"""A new project's edit spec starts plain: no intro/outro cards and no automatic
zooms until the user opts in. Click positions are still kept as zoom targets."""

from __future__ import annotations

from app.editspec import build_edit_spec

GRAPH = {
    "version": 1,
    "title": "Demo",
    "steps": [
        {"id": "s1", "action": "click", "target": "Save", "narration": "Click save.",
         "t_start": 0.0, "t_end": 3.0, "bbox": [100, 100, 40, 20]},
    ],
}


def test_cards_and_auto_zoom_are_off_by_default():
    spec = build_edit_spec(GRAPH, {"w": 1280, "h": 720})
    assert spec["intro"]["enabled"] is False
    assert spec["outro"]["enabled"] is False
    assert spec["motion_zoom"] is False


def test_click_zoom_is_off_but_keeps_its_target():
    spec = build_edit_spec(GRAPH, {"w": 1280, "h": 720})
    zoom = spec["segments"][0]["zoom"]
    assert zoom["enabled"] is False
    # centre of the 40x20 box at (100,100) in a 1280x720 viewport
    assert (zoom["cx"], zoom["cy"]) == (round(120 / 1280, 4), round(110 / 720, 4))
