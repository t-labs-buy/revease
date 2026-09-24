"""Pure parts of documentation snapshots: moment selection, bbox normalisation,
the highlight overlay and JPEG encoding. No ffmpeg needed."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from worker.pipeline.docshots import (
    BRAND_TEAL,
    annotate,
    annotate_policy,
    bbox_to_frame_norm,
    encode_jpeg,
    nearest_keyframe,
    pick_snapshot_time,
    snapshot_keys,
)

CLICKS = [(1200, 0.5, 0.5), (5300, 0.2, 0.2)]


@pytest.mark.parametrize(
    "step, expected_t, reason",
    [
        ({"action": "click", "t_start": 1.0, "t_end": 4.0}, 1.35, "click"),  # click at 1.2s + 150ms
        ({"action": "click", "t_start": 5.2, "t_end": 8.0}, 5.45, "click"),
        ({"action": "click", "t_start": 2.0, "t_end": 4.0}, 2.5, "start_offset"),  # no click in window
        ({"action": "click", "t_start": 2.0, "t_end": 2.4}, 2.2, "start_offset"),  # short window: half span
        ({"action": "input", "t_start": 9.0, "t_end": 14.5}, 14.3, "input_end"),
        ({"action": "input", "t_start": 9.0, "t_end": 9.1}, 9.0, "input_end"),  # never before the start
        ({"action": "navigation", "t_start": 20.0, "t_end": 26.0}, 21.0, "nav_settled"),
        ({"action": "navigation", "t_start": 20.0, "t_end": 20.5}, 20.5, "nav_settled"),  # capped at t_end
        ({"action": "navigation", "t_start": 20.0, "t_end": None}, 21.0, "nav_settled"),  # unknown end
        ({"action": "scroll", "t_start": 30.0, "t_end": 30.4}, 30.2, "start_offset"),
        ({"action": "custom", "t_start": None, "t_end": None}, 0.0, "start_offset"),
    ],
)
def test_pick_snapshot_time(step, expected_t, reason):
    t, r = pick_snapshot_time(step, CLICKS, 60.0)
    assert (t, r) == (expected_t, reason)


def test_pick_snapshot_time_clamps_to_duration():
    t, _ = pick_snapshot_time({"action": "input", "t_start": 58.0, "t_end": 70.0}, [], 60.0)
    assert t == 59.95
    t, _ = pick_snapshot_time({"action": "click", "t_start": 1.0, "t_end": 4.0}, CLICKS, 0.0)
    assert t == 1.35  # unknown duration: no upper clamp


def test_bbox_to_frame_norm():
    assert bbox_to_frame_norm([64, 36, 128, 72], {"w": 1280, "h": 720}) == [0.05, 0.05, 0.1, 0.1]
    assert bbox_to_frame_norm([100, 100, 0, 0], {"w": 200, "h": 200}) == [0.5, 0.5, 0.0, 0.0]  # point kept
    assert bbox_to_frame_norm([64, 36, 128, 72], None) is None
    assert bbox_to_frame_norm([64, 36, 128, 72], {"w": 0, "h": 720}) is None
    assert bbox_to_frame_norm([1, 2, 3], {"w": 10, "h": 10}) is None
    assert bbox_to_frame_norm([-5, 5000, 10, 10], {"w": 100, "h": 100}) == [0.0, 1.0, 0.1, 0.1]


def test_annotate_policy_by_source():
    assert annotate_policy("extension") and annotate_policy("auto")
    assert not annotate_policy("recorder") and not annotate_policy("upload") and not annotate_policy(None)


def _white(w: int = 400, h: int = 200) -> Image.Image:
    return Image.new("RGB", (w, h), (255, 255, 255))


def _near(px: tuple[int, int, int], target: tuple[int, int, int], tol: int = 12) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(px, target))


def test_annotate_draws_box_border_and_tinted_fill():
    img = _white()
    out = annotate(img, [0.25, 0.25, 0.5, 0.5])  # box 100..300 x 50..150, padded by 8
    assert out.size == img.size and out.mode == "RGB"
    assert img.getpixel((200, 100)) == (255, 255, 255)  # input untouched
    assert _near(out.getpixel((200, 42)), BRAND_TEAL, tol=40)  # top border (y = 50 - 8)
    centre = out.getpixel((200, 100))
    assert centre != (255, 255, 255) and not _near(centre, BRAND_TEAL, tol=40)  # tinted, not solid
    assert out.getpixel((10, 10)) == (255, 255, 255)  # outside untouched


def test_annotate_ring_for_point_click_and_min_size():
    out = annotate(_white(), [0.5, 0.5, 0.0, 0.0])
    assert _near(out.getpixel((200, 100 - 28 + 2)), BRAND_TEAL, tol=40)  # ring edge above the centre
    assert out.getpixel((200, 100)) != (255, 255, 255)  # faint fill inside
    tiny = annotate(_white(), [0.5, 0.5, 0.005, 0.005])  # 2x1 px box grows to the 24px minimum
    assert tiny.getpixel((200, 100)) != (255, 255, 255)


def test_annotate_without_bbox_is_a_plain_copy():
    out = annotate(_white(), None)
    assert out.getpixel((200, 100)) == (255, 255, 255) and out.mode == "RGB"


def test_encode_jpeg_caps_width():
    b = encode_jpeg(_white(3200, 1600), max_w=1600)
    im = Image.open(io.BytesIO(b))
    assert im.format == "JPEG" and im.size == (1600, 800)
    small = Image.open(io.BytesIO(encode_jpeg(_white(300, 100), max_w=1600)))
    assert small.size == (300, 100)


def test_snapshot_keys_and_nearest_keyframe():
    assert snapshot_keys("sid", "s3", 12.49) == (
        "sessions/sid/docshots/s3_12490.jpg",
        "sessions/sid/docshots/s3_12490_raw.jpg",
    )
    kf = [(0.0, "a"), (1.0, "b"), (2.0, "c")]
    assert nearest_keyframe(1.4, kf) == "b" and nearest_keyframe(1.6, kf) == "c"
    assert nearest_keyframe(1.0, []) is None
