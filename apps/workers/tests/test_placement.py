"""Exhaustive checks for worker.pipeline.placement (pure)."""

from app.editspec import effective_inserts
from worker.pipeline.placement import Placed, enable_expr, insert_slots, overlay_box, overlay_windows


def _spec(inserts, ids=("a", "b", "c"), intro=False, outro=False):
    return {
        "segments": [{"step_id": i} for i in ids],
        "inserts": inserts,
        "intro": {"enabled": intro, "title": "Hi", "duration_ms": 1500},
        "outro": {"enabled": outro, "title": "Bye", "duration_ms": 1000},
    }


def test_effective_inserts_order_and_legacy_cards():
    ins = [
        {"id": "e", "type": "title", "position": "end"},
        {"id": "m", "type": "image", "media_key": "k", "position": "after:b"},
        {"id": "s", "type": "title", "position": "start"},
        {"id": "x", "type": "video", "position": "after:a"},  # no media -> dropped
        {"id": "o", "type": "image", "media_key": "k", "position": "after:zzz"},  # orphan
    ]
    out = effective_inserts(_spec(ins, intro=True, outro=True))
    assert [i["id"] for i in out] == ["intro", "s", "m", "o", "e", "outro"]
    assert [i["slot"] for i in out] == [-1, -1, 1, 2, 2, 2]
    assert out[0]["type"] == "title" and out[0]["title"] == "Hi"
    # an insert that replaced the legacy card wins
    out = effective_inserts(_spec([{"id": "intro", "type": "title", "position": "start"}], intro=True))
    assert [i["id"] for i in out] == ["intro"] and "legacy" not in out[0]


def test_legacy_media_card_becomes_media_insert():
    spec = _spec([])
    spec["intro"] = {"enabled": True, "duration_ms": 2000, "media_key": "p/v.mp4", "media_type": "video"}
    (it,) = effective_inserts(spec)
    assert it["type"] == "video" and it["media_key"] == "p/v.mp4" and it["keep_audio"] is True


def test_insert_slots_follow_skipped_scenes():
    items = [{"slot": -1}, {"slot": 0}, {"slot": 1}, {"slot": 2, "position": "end"}]
    # scene "b" (index 1) skipped: its insert goes after "a"
    out = insert_slots(items, ["a", "b", "c"], ["a", "c"])
    assert [s for s, _ in out] == [-1, 0, 0, 1]
    # only the last scene rendered: early inserts go to the start, the outro stays last
    out = insert_slots(items, ["a", "b", "c"], ["c"])
    assert [s for s, _ in out] == [-1, -1, -1, 0]
    # nothing rendered at all
    assert [s for s, _ in insert_slots(items, ["a"], [])] == [-1, -1, -1, -1]


P = [
    Placed("insert", 0, 1000),
    Placed("scene", 1000, 3000, 0, 4000),       # source 0-4s squeezed into 2s
    Placed("insert", 3000, 3500),
    Placed("scene", 3500, 5500, 4000, 6000),    # source 4-6s at 1x
]


def test_overlay_windows_ranges():
    assert overlay_windows(P, "all") == [(0, 5500)]
    assert overlay_windows(P, "body") == [(1000, 3000), (3500, 5500)]
    assert overlay_windows(P, {"start_ms": 2000, "end_ms": 5000}) == [(2000, 3000), (3500, 4500)]
    assert overlay_windows(P, {"start_ms": 0, "end_ms": 2000}) == [(1000, 2000)]
    assert overlay_windows(P, {"start_ms": 7000, "end_ms": 9000}) == []   # past the end
    assert overlay_windows(P, {"start_ms": 3000, "end_ms": 3000}) == []   # zero length
    assert overlay_windows(P, {"start_ms": "x"}) == []
    assert overlay_windows([], "all") == []
    assert overlay_windows(P, "weird") == [(0, 5500)]


def test_adjacent_scenes_merge_and_stills_count():
    placed = [Placed("scene", 0, 1000, 0, 1000), Placed("scene", 1000, 2000, 1000, 1000)]
    assert overlay_windows(placed, "body") == [(0, 2000)]
    # the second scene is a still at source 1000 — inside the range
    assert overlay_windows(placed, {"start_ms": 500, "end_ms": 1200}) == [(500, 2000)]


def test_enable_expr_and_box():
    assert enable_expr([(0, 1500), (2000, 2500)]) == "between(t,0.000,1.500)+between(t,2.000,2.500)"
    assert enable_expr([]) == "0"
    assert overlay_box({"x": 0.8, "y": 0.05, "w": 0.15, "h": 0.1}, (1920, 1080)) == (1536, 54, 288, 108)
    x, y, w, h = overlay_box({"x": 0.99, "y": 0.99, "w": 0.5, "h": 0.5}, (1920, 1080))
    assert x + w <= 1920 and y + h <= 1080  # clamped into the frame
    assert overlay_box({"w": 0, "h": 0}, (1920, 1080))[2:] == (8, 8)
