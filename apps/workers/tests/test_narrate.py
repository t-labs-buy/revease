"""narrate.py runs its deterministic fallback here (conftest strips API keys)."""

from worker.pipeline.narrate import _even_split, _is_verbatim_partition, narrate_steps


def _steps(n):
    return [{"action": "click", "intent": f"do {i}", "plan_item_id": "p1"} for i in range(n)]


def test_empty_transcript_yields_empty_per_step():
    assert narrate_steps(_steps(3), [], "") == ["", "", ""]


def test_no_steps_yields_empty_list():
    assert narrate_steps([], [], "hello world.") == []


def test_fallback_is_verbatim_partition():
    transcript = "Welcome to the app. Click new invoice. Fill in the amount. Save it and you are done."
    out = narrate_steps(_steps(4), [], transcript)
    assert len(out) == 4
    assert _is_verbatim_partition(out, transcript)


def test_more_steps_than_sentences_allows_empty_slices():
    transcript = "One sentence only here."
    out = narrate_steps(_steps(5), [], transcript)
    assert len(out) == 5
    assert _is_verbatim_partition(out, transcript)
    assert sum(1 for s in out if s) == 1  # only one non-empty slice


def test_even_split_covers_all_words_in_order():
    transcript = "Alpha beta. Gamma delta. Epsilon zeta."
    chunks = _even_split(transcript, 3)
    assert " ".join(chunks).split() == transcript.split()


def test_verbatim_check_rejects_reworded():
    assert not _is_verbatim_partition(["Click the button now"], "Click the button")
