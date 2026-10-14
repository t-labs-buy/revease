"""Script -> scene windows. The properties that must hold for every input: windows
are in order, contiguous, cover the kept video, and the narration is the script
word-for-word."""

from worker.pipeline.scriptalign import (
    ScriptLine,
    fit_lines,
    parse_script,
    proportional_starts,
    script_steps,
    script_text,
    snap_starts,
    to_kept,
    to_source,
    valid_starts,
)

SCRIPT = (
    "Welcome to the billing dashboard. Open the invoices tab to see every invoice. "
    "Click an invoice to view its line items. Finally, download it as a PDF."
)


def _narration(steps):
    return " ".join(s["narration_span"] for s in steps if s["narration_span"]).split()


def _assert_partition(steps, spans):
    assert steps[0]["t_start"] == spans[0][0]
    assert steps[-1]["t_end"] == spans[-1][1]
    for a, b in zip(steps, steps[1:]):
        assert a["t_end"] <= b["t_start"]  # equal, or a removed gap between spans
        assert a["t_start"] <= a["t_end"]


# ---- parsing ----------------------------------------------------------------
def test_plain_script_splits_into_sentences_verbatim():
    lines = parse_script(SCRIPT)
    assert len(lines) == 4 and all(ln.t_start is None for ln in lines)
    assert script_text(lines).split() == SCRIPT.split()


def test_short_fragments_are_packed_into_a_neighbour():
    lines = parse_script("Great. Now open the settings page from the menu. Done. Save your changes here now.")
    assert [ln.text for ln in lines] == [
        "Great. Now open the settings page from the menu. Done.",
        "Save your changes here now.",
    ]


def test_bracket_and_bare_timestamps_pin_lines():
    lines = parse_script("[0:05] Open the dashboard first.\n1:10 - Then export the report now.\nIt downloads as a file.")
    assert [(ln.t_start, ln.text) for ln in lines] == [
        (5.0, "Open the dashboard first."),
        (70.0, "Then export the report now."),
        (None, "It downloads as a file."),
    ]


def test_srt_cues_become_pinned_lines():
    srt = "1\n00:00:01,500 --> 00:00:04,000\nOpen the dashboard\nfrom the menu.\n\n2\n00:00:09,000 --> 00:00:12,000\nExport the report.\n"
    lines = parse_script(srt)
    assert [(ln.t_start, ln.t_end, ln.text) for ln in lines] == [
        (1.5, 4.0, "Open the dashboard from the menu."),
        (9.0, 12.0, "Export the report."),
    ]


STORYBOARD = (
    "Time\tOn screen\tVoiceover\n"
    "0:00 – 0:03\tRecorder overlay, recording starts\t\"Let's see how quickly you can set up a test.\"\n"
    "0:03 – 0:06\tDashboard, Integrations menu opens\t\"From the dashboard, open the Integrations menu…\"\n"
    "0:06 – 0:08\tA2A Test Suites list loads\t\"…and go to Test Suites. Here you can see every suite your team built.\"\n"
    "0:08 – 0:10\tClick \"Create New Test Suite\"\t\"To add one, click Create New Test Suite.\"\n"
)


def test_storyboard_table_keeps_only_the_voiceover_column():
    lines = parse_script(STORYBOARD)
    assert [ln.text for ln in lines] == [
        "Let's see how quickly you can set up a test.",
        "From the dashboard, open the Integrations menu…",
        "…and go to Test Suites.",
        "Here you can see every suite your team built.",
        "To add one, click Create New Test Suite.",
    ]
    # start times pinned; the end of each range and the header row are dropped
    assert [ln.t_start for ln in lines] == [0.0, 3.0, 6.0, None, 8.0]
    steps = script_steps(lines, [(0.0, 10.0)], [], [])
    assert [s["t_start"] for s in steps][:3] == [0.0, 3.0, 6.0] and steps[-1]["t_start"] == 8.0


def test_bracketed_time_ranges_are_pins_not_words():
    text = (
        "[0:00 - 0:03]  Let's see how quickly you can set up a test in TestEase.\n\n"
        "[0:03 - 0:06]  From the dashboard, open the Integrations menu...\n\n"
        "[0:06 - 0:08]  ...and go to Test Suites. Here you can see every suite your team has built.\n\n"
        "(0:08 – 0:10)  To add one, click Create New Test Suite.\n"
    )
    lines = parse_script(text)
    assert [ln.t_start for ln in lines] == [0.0, 3.0, 6.0, None, 8.0]
    # the end closes the chunk's LAST sentence; a lone one carries both
    assert [ln.t_end for ln in lines] == [3.0, 6.0, None, 8.0, 10.0]
    joined = script_text(lines)
    assert ":" not in joined.replace("TestEase.", "") and "[" not in joined and "]" not in joined
    assert lines[0].text == "Let's see how quickly you can set up a test in TestEase."
    assert lines[-1].text == "To add one, click Create New Test Suite."


def test_end_time_before_the_next_line_leaves_a_blank_scene():
    lines = parse_script("[0:00 - 0:03] Open the dashboard now.\n[0:08 - 0:10] Export the report please.")
    steps = script_steps(lines, [(0.0, 20.0)], [], [])
    assert [(s["t_start"], s["t_end"], s["narration_span"]) for s in steps] == [
        (0.0, 3.0, "Open the dashboard now."),
        (3.0, 8.0, ""),  # the gap: footage with nothing written for it
        (8.0, 10.0, "Export the report please."),
        (10.0, 20.0, ""),  # the last line's end time, before the video ends
    ]
    assert steps[1]["target"] == "Silence — add narration"
    _assert_partition(steps, [(0.0, 20.0)])


def test_end_times_that_meet_the_next_line_add_no_blank():
    lines = parse_script("[0:00 - 0:03] Open the dashboard now.\n[0:03 - 0:06] Export the report please.")
    steps = script_steps(lines, [(0.0, 6.0)], [], [])
    assert [(s["t_start"], s["t_end"]) for s in steps] == [(0.0, 3.0), (3.0, 6.0)]
    # an end past the next start, or a tiny gap, is ignored too
    lines = parse_script("[0:00 - 0:04] Open the dashboard now.\n[0:03 - 0:06] Export the report please.")
    assert [(s["t_start"], s["t_end"]) for s in script_steps(lines, [(0.0, 6.0)], [], [])] == [(0.0, 3.0), (3.0, 6.0)]
    lines = parse_script("[0:00 - 0:02.8] Open the dashboard now.\n[0:03 - 0:06] Export the report please.")
    assert [(s["t_start"], s["t_end"]) for s in script_steps(lines, [(0.0, 6.0)], [], [])] == [(0.0, 3.0), (3.0, 6.0)]


def test_srt_cue_ends_are_honoured():
    srt = "1\n00:00:01,500 --> 00:00:03,000\nOpen the dashboard now.\n\n2\n00:00:06,000 --> 00:00:09,000\nExport the report please.\n"
    steps = script_steps(parse_script(srt), [(0.0, 9.0)], [], [])
    assert [(s["t_start"], s["t_end"], bool(s["narration_span"])) for s in steps] == [
        (0.0, 1.5, False), (1.5, 3.0, True), (3.0, 6.0, False), (6.0, 9.0, True),
    ]


def test_pipe_table_and_plain_timed_lines_still_parse():
    lines = parse_script("0:05 | Dashboard | Open the dashboard now.\n0:12 - Export the report please.")
    assert [(ln.t_start, ln.text) for ln in lines] == [
        (5.0, "Open the dashboard now."),
        (12.0, "Export the report please."),
    ]
    # a time mentioned in prose, after the stamp, is not an end time
    assert parse_script("0:05 Wait until 0:30 then save the form.")[0].text == "Wait until 0:30 then save the form."


def test_out_of_order_pin_is_dropped_but_line_kept():
    lines = parse_script("[0:20] First line of the script.\n[0:10] Second line of the script.")
    assert [ln.t_start for ln in lines] == [20.0, None]
    assert len(lines) == 2


def test_pause_marker_survives_and_is_not_a_sentence_break():
    lines = parse_script("Open the menu. [pause:1.5] Then choose the export option here.")
    assert script_text(lines) == "Open the menu. [pause:1.5] Then choose the export option here."


def test_empty_script():
    assert parse_script("") == [] and parse_script("  \n ") == []
    assert script_steps([], [(0.0, 10.0)], [], []) == []


# ---- timing -----------------------------------------------------------------
def test_proportional_windows_partition_the_video_by_word_share():
    lines = [ScriptLine("one two three four"), ScriptLine("five six seven eight nine ten eleven twelve")]
    steps = script_steps(lines, [(0.0, 30.0)], [], [])
    assert [(s["t_start"], s["t_end"]) for s in steps] == [(0.0, 10.0), (10.0, 30.0)]
    _assert_partition(steps, [(0.0, 30.0)])


def test_narration_is_verbatim_and_frames_attached():
    lines = parse_script(SCRIPT)
    kf = [(float(t), f"f{t}") for t in range(0, 40)]
    steps = script_steps(lines, [(0.0, 40.0)], kf, [])
    assert _narration(steps) == SCRIPT.split()
    assert len(steps) == 4 and all(s["screenshot"] for s in steps)
    assert steps[0]["target"] == "Welcome to the billing dashboard."
    _assert_partition(steps, [(0.0, 40.0)])


def test_boundary_snaps_to_a_nearby_scene_cut_only():
    lines = [ScriptLine("a b c d e"), ScriptLine("f g h i j")]
    near = script_steps(lines, [(0.0, 20.0)], [], [11.2])
    assert near[1]["t_start"] == 11.2
    far = script_steps(lines, [(0.0, 20.0)], [], [15.0])  # beyond tolerance: stays proportional
    assert far[1]["t_start"] == 10.0


def test_snap_tolerance_shrinks_with_short_scenes():
    # scenes of 1s each: tolerance is 0.4s, so a cut 0.5s from either boundary is ignored
    assert snap_starts([0.0, 1.0, 2.0], [False] * 3, [1.5], 3.0) == [0.0, 1.0, 2.0]
    assert snap_starts([0.0, 1.0, 2.0], [False] * 3, [1.3], 3.0)[1] == 1.3


def test_pinned_line_keeps_its_time_and_neighbours_fill_between():
    lines = [ScriptLine("intro words here now"), ScriptLine("middle words here now"),
             ScriptLine("pinned words here now", 24.0), ScriptLine("last words here now")]
    steps = script_steps(lines, [(0.0, 40.0)], [], [23.0])  # a cut must not move the pin
    assert [s["t_start"] for s in steps] == [0.0, 12.0, 24.0, 32.0]
    _assert_partition(steps, [(0.0, 40.0)])


def test_late_first_pin_gets_a_blank_lead_in():
    lines = [ScriptLine("first line of script", 6.0), ScriptLine("second line of script")]
    steps = script_steps(lines, [(0.0, 20.0)], [], [])
    assert steps[0]["narration_span"] == "" and (steps[0]["t_start"], steps[0]["t_end"]) == (0.0, 6.0)
    assert steps[1]["t_start"] == 6.0 and len(steps) == 3
    _assert_partition(steps, [(0.0, 20.0)])


def test_llm_starts_used_when_valid_and_ignored_when_not():
    lines = [ScriptLine("a b c d"), ScriptLine("e f g h"), ScriptLine("i j k l")]
    spans = [(0.0, 30.0)]
    good = script_steps(lines, spans, [], [], llm_starts=[0.0, 4.0, 22.0])
    assert [s["t_start"] for s in good] == [0.0, 4.0, 22.0]
    for bad in ([0.0, 22.0, 4.0], [0.0, 4.0], [0.0, 4.0, 99.0], [0.0, "4", 22.0]):
        assert [s["t_start"] for s in script_steps(lines, spans, [], [], llm_starts=bad)] == [0.0, 10.0, 20.0]


def test_valid_starts():
    assert valid_starts([0, 1.5, 1.5, 9], 4, 10.0)
    assert not valid_starts([0, 2, 1], 3, 10.0)
    assert not valid_starts([0, float("nan")], 2, 10.0)
    assert not valid_starts([0, True], 2, 10.0)
    assert not valid_starts(None, 0, 10.0)


def test_more_lines_than_the_video_can_hold_are_merged_verbatim():
    lines = [ScriptLine(f"line number {i} here") for i in range(10)]
    steps = script_steps(lines, [(0.0, 4.0)], [], [], llm_starts=[0.0] * 10)
    assert len(steps) == 4
    assert _narration(steps) == script_text(lines).split()
    _assert_partition(steps, [(0.0, 4.0)])


def test_fit_lines_prefers_folding_unpinned_lines():
    lines = [ScriptLine("a b"), ScriptLine("c d", 5.0), ScriptLine("e"), ScriptLine("f g h", 9.0)]
    out = fit_lines(lines, 3)
    assert [(ln.text, ln.t_start) for ln in out] == [("a b", None), ("c d e", 5.0), ("f g h", 9.0)]


# ---- trim / keep ranges -----------------------------------------------------
def test_kept_axis_round_trip():
    spans = [(2.0, 6.0), (10.0, 14.0)]
    assert to_kept(1.0, spans) == 0.0 and to_kept(4.0, spans) == 2.0
    assert to_kept(8.0, spans) == 4.0 and to_kept(12.0, spans) == 6.0
    assert to_source(2.0, spans) == 4.0
    assert to_source(4.0, spans) == 10.0  # a window START on the edge opens the next span
    assert to_source(4.0, spans, end=True) == 6.0  # a window END on the edge closes the previous
    assert to_source(8.0, spans, end=True) == 14.0


def test_windows_never_land_in_removed_footage():
    spans = [(2.0, 6.0), (10.0, 14.0)]
    lines = [ScriptLine("a b c d"), ScriptLine("e f g h"), ScriptLine("i j k l"), ScriptLine("m n o p")]
    steps = script_steps(lines, spans, [], [])
    assert [(s["t_start"], s["t_end"]) for s in steps] == [(2.0, 4.0), (4.0, 6.0), (10.0, 12.0), (12.0, 14.0)]
    _assert_partition(steps, spans)


def test_boundary_snaps_onto_the_edge_of_removed_footage():
    spans = [(0.0, 9.0), (20.0, 31.0)]
    steps = script_steps([ScriptLine("a b c d e"), ScriptLine("f g h i j")], spans, [], [])
    assert (steps[0]["t_start"], steps[0]["t_end"]) == (0.0, 9.0)
    assert (steps[1]["t_start"], steps[1]["t_end"]) == (20.0, 31.0)


def test_pin_inside_removed_footage_or_past_the_end_is_dropped():
    spans = [(0.0, 10.0)]
    lines = [ScriptLine("a b c d"), ScriptLine("e f g h", 99.0)]
    assert [s["t_start"] for s in script_steps(lines, spans, [], [])] == [0.0, 5.0]


def test_proportional_starts_between_pins():
    assert proportional_starts([1, 1, 1, 1], [None, None, 8.0, None], 10.0) == [0.0, 4.0, 8.0, 9.0]
