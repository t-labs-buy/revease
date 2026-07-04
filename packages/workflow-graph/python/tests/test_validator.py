import copy

from refract_workflow_graph import assert_valid, load_example, validate


def test_accepts_master_example():
    result = validate(load_example())
    assert result.valid, result.errors


def test_rejects_missing_action():
    bad = copy.deepcopy(load_example())
    del bad["steps"][0]["action"]
    assert not validate(bad).valid


def test_rejects_unknown_action():
    bad = copy.deepcopy(load_example())
    bad["steps"][0]["action"] = "teleport"
    assert not validate(bad).valid


def test_rejects_bad_bbox_length():
    bad = copy.deepcopy(load_example())
    bad["steps"][0]["bbox"] = [1, 2, 3]
    assert not validate(bad).valid


def test_assert_valid_raises_on_invalid():
    try:
        assert_valid({"workflow_id": "x"})
    except ValueError:
        return
    raise AssertionError("expected ValueError")
