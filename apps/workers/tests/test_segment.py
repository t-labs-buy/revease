from worker.pipeline.providers import Transcript, Word
from worker.pipeline.segment import segment


def _clicks(*t_ms):
    return [
        {"seq": i, "type": "click", "t_ms": t, "selector": f"#b{i}", "text": f"Button {i}", "bbox": [i * 10, i * 10, 8, 8]}
        for i, t in enumerate(t_ms)
    ]


def test_click_boundaries_split_into_steps():
    steps = segment(_clicks(1000, 3000, 5000), Transcript(), [], {}, 7.0, "present")
    assert len(steps) == 3
    # first step starts at 0 (captures leading narration); boundaries at clicks
    assert steps[0]["t_start"] == 0.0 and steps[0]["t_end"] == 3.0
    assert steps[1]["t_start"] == 3.0 and steps[1]["t_end"] == 5.0
    # final step runs to duration so trailing narration is attached
    assert steps[2]["t_start"] == 5.0 and steps[2]["t_end"] == 7.0


def test_leading_and_trailing_narration_attached():
    tx = Transcript(
        words=[
            Word("Hello", 0.2, 0.6),  # before first click -> step 1
            Word("world.", 0.6, 1.0),
            Word("Bye.", 6.0, 6.4),  # after last click -> final step
        ],
        text="Hello world. Bye.",
    )
    steps = segment(_clicks(1000, 5000), tx, [], {}, 7.0, "present")
    assert "Hello world." in steps[0]["narration_span"]
    assert "Bye." in steps[-1]["narration_span"]


def test_no_clicks_present_flag_falls_back_to_transcript():
    tx = Transcript(
        words=[Word("Open", 0.0, 0.4), Word("settings.", 0.4, 1.0), Word("Then", 1.2, 1.5), Word("save.", 1.5, 2.0)],
        text="Open settings. Then save.",
    )
    steps = segment([], tx, [], {}, 2.0, "absent")
    assert len(steps) == 2  # two sentences
    assert steps[0]["narration_span"].startswith("Open")


def test_absent_no_transcript_uses_scene_keyframes():
    kfs = [(0.0, "f0.jpg"), (2.5, "f1.jpg")]
    steps = segment([], Transcript(), kfs, {}, 5.0, "absent")
    assert len(steps) == 2
    assert steps[0]["screenshot"] == "f0.jpg" and steps[1]["t_end"] == 5.0


def test_absent_no_data_single_step():
    steps = segment([], Transcript(), [], {}, 3.0, "absent")
    assert len(steps) == 1 and steps[0]["t_end"] == 3.0


def test_scene_segmentation_is_capped_not_one_per_frame():
    # 4461 keyframes (the real-world bug) must NOT produce 4461 steps.
    kfs = [(i * 0.066, f"f{i}.jpg") for i in range(4461)]
    steps = segment([], Transcript(), kfs, {}, 300.0, "absent")
    assert 1 < len(steps) <= 20
    assert steps[-1]["t_end"] == 300.0  # final step runs to the end


def test_screenshot_by_seq_preferred_over_frame():
    steps = segment(_clicks(1000), Transcript(), [(0.9, "frame.jpg")], {0: "shot0.png"}, 2.0, "present")
    assert steps[0]["screenshot"] == "shot0.png"


def test_zero_duration_and_single_click_ok():
    steps = segment(_clicks(0), Transcript(), [], {}, 0.0, "present")
    assert len(steps) == 1
    assert steps[0]["t_start"] == 0.0 and steps[0]["t_end"] == 0.0


def test_scene_cuts_drive_boundaries_when_supplied():
    kfs = [(float(t), f"f{t}.jpg") for t in range(0, 60)]
    # 12.0 and 12.5 are one scene (too close); 58.0 is too near the end
    steps = segment([], Transcript(), kfs, {}, 60.0, "absent", cuts=[12.0, 12.5, 30.0, 58.0])
    assert [(s["t_start"], s["t_end"]) for s in steps] == [(0.0, 12.0), (12.0, 30.0), (30.0, 60.0)]
    assert steps[1]["screenshot"] == "f13.jpg"  # a beat after the cut, not the transition frame
    assert all(s["narration_span"] == "" for s in steps)


def test_scene_cuts_are_capped_by_merging_the_shortest_scenes():
    kfs = [(float(t), f"f{t}.jpg") for t in range(0, 300)]
    steps = segment([], Transcript(), kfs, {}, 300.0, "absent", cuts=[float(t) for t in range(3, 297, 3)])
    assert len(steps) == 20 and steps[0]["t_start"] == 0.0 and steps[-1]["t_end"] == 300.0
    assert all(a["t_end"] == b["t_start"] for a, b in zip(steps, steps[1:]))
