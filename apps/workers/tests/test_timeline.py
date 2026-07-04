"""Exhaustive edge-case matrix for buildTimeline (master §Phase-4 E5).
This is the most important test suite in P3 — the render hangs off it."""

from worker.pipeline.timeline import StepInput, build_timeline


def _step(**kw):
    base = dict(step_id="s", tts_duration_ms=1000, source_start_ms=0, source_end_ms=1000)
    base.update(kw)
    return StepInput(**base)


def test_empty_steps():
    tl = build_timeline([])
    assert tl.segments == [] and tl.total_duration_ms == 0


def test_no_drift_cumulative_clock():
    steps = [
        _step(step_id="s1", tts_duration_ms=1200),
        _step(step_id="s2", tts_duration_ms=800),
        _step(step_id="s3", tts_duration_ms=2000),
    ]
    tl = build_timeline(steps)
    # cumulative starts/ends line up with zero gaps
    assert [s.out_start_ms for s in tl.segments] == [0, 1200, 2000]
    assert [s.out_end_ms for s in tl.segments] == [1200, 2000, 4000]
    # total == sum of durations, exactly (no drift)
    assert tl.total_duration_ms == 1200 + 800 + 2000
    assert tl.total_duration_ms == sum(s.out_duration_ms for s in tl.segments)


def test_no_clicks_means_no_zoom():
    tl = build_timeline([_step(click_x=None, click_y=None)])
    assert tl.segments[0].zoom is None


def test_click_produces_normalized_zoom_center():
    tl = build_timeline([_step(click_x=640, click_y=360, viewport_w=1280, viewport_h=720)])
    z = tl.segments[0].zoom
    assert z is not None and z["cx"] == 0.5 and z["cy"] == 0.5 and z["scale"] >= 1.0


def test_click_coord_out_of_bounds_is_clamped():
    tl = build_timeline([_step(click_x=5000, click_y=-40, viewport_w=1280, viewport_h=720)])
    z = tl.segments[0].zoom
    assert z["cx"] == 1.0 and z["cy"] == 0.0


def test_back_to_back_clicks_zero_source_window_holds():
    # two steps whose source windows collapse to a point
    steps = [
        _step(step_id="s1", tts_duration_ms=900, source_start_ms=2000, source_end_ms=2000),
        _step(step_id="s2", tts_duration_ms=900, source_start_ms=2000, source_end_ms=2000),
    ]
    tl = build_timeline(steps)
    assert all(s.hold and s.speed == 1.0 for s in tl.segments)
    assert tl.total_duration_ms == 1800  # still exact


def test_zero_duration_step_does_not_break_clock():
    steps = [
        _step(step_id="s1", tts_duration_ms=1000),
        _step(step_id="s2", tts_duration_ms=0),  # zero-duration TTS
        _step(step_id="s3", tts_duration_ms=500),
    ]
    tl = build_timeline(steps)
    z = tl.segments[1]
    assert z.out_start_ms == 1000 and z.out_end_ms == 1000 and z.hold
    assert tl.total_duration_ms == 1500


def test_trailing_narration_slow_speed_when_source_shorter_than_audio():
    # long narration (audio) over a short source window -> speed < 1 (slowed to fill)
    tl = build_timeline([_step(tts_duration_ms=4000, source_start_ms=0, source_end_ms=1000)])
    seg = tl.segments[0]
    assert not seg.hold and 0 < seg.speed < 1


def test_fast_speed_when_source_longer_than_audio():
    tl = build_timeline([_step(tts_duration_ms=1000, source_start_ms=0, source_end_ms=5000)])
    assert tl.segments[0].speed == 5.0


def test_reversed_source_window_is_normalized():
    tl = build_timeline([_step(source_start_ms=3000, source_end_ms=1000)])
    seg = tl.segments[0]
    assert seg.source_start_ms == 1000 and seg.source_end_ms == 3000


def test_zoom_disabled_flag_suppresses_zoom():
    tl = build_timeline(
        [_step(click_x=100, click_y=100, viewport_w=1280, viewport_h=720, zoom_enabled=False)]
    )
    assert tl.segments[0].zoom is None


def test_leading_narration_first_step_from_zero():
    # first step covers 0..click (segmentation sets source_start=0); timeline preserves it
    tl = build_timeline([_step(step_id="s1", source_start_ms=0, source_end_ms=2000)])
    assert tl.segments[0].source_start_ms == 0
