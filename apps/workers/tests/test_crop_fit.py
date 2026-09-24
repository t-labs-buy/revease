"""A crop region is shown whole (fit + letterbox), never cut down again to the
output aspect; zoom centers are remapped into that fitted frame."""

from __future__ import annotations

import pytest

from worker.pipeline.render import _fit_filter, _remap_zoom_into_crop

WIDE = {"enabled": True, "x": 0.1, "y": 0.4, "w": 0.8, "h": 0.2}  # 4:1 strip


def test_crop_region_is_fitted_whole_not_covered():
    f = _fit_filter(WIDE, 1920, 1080)
    assert "force_original_aspect_ratio=decrease" in f
    assert "pad=1920:1080:(ow-iw)/2:(oh-ih)/2" in f


def test_no_crop_still_covers_the_frame():
    f = _fit_filter(None, 1920, 1080)
    assert "force_original_aspect_ratio=increase,crop=1920:1080" in f
    assert _fit_filter({"enabled": True, "x": 0, "y": 0, "w": 1, "h": 1}, 1920, 1080) == f


def test_zoom_center_follows_the_fitted_region():
    # the strip is scaled by k = 1/0.8 = 1.25 and centered; a click at its exact
    # centre stays at the frame centre, and one at its left edge lands at the
    # frame's left edge (0.5 - 0.4 * 1.25 = 0)
    z = _remap_zoom_into_crop({"enabled": True, "cx": 0.5, "cy": 0.5, "scale": 1.6}, WIDE)
    assert (z["cx"], z["cy"]) == pytest.approx((0.5, 0.5))
    z = _remap_zoom_into_crop({"enabled": True, "cx": 0.1, "cy": 0.4, "scale": 1.6}, WIDE)
    assert z["cx"] == pytest.approx(0.0)
    assert z["cy"] == pytest.approx(0.5 - 0.1 * 1.25)


def test_zoom_untouched_without_crop():
    z = {"enabled": True, "cx": 0.2, "cy": 0.3}
    assert _remap_zoom_into_crop(z, None) == z
