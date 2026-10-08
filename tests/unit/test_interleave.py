import pytest

from app.domain.interleave import interleave, render_output


def test_interleave_alternates_starting_with_the_first_list():
    assert interleave(["a", "b"], ["x", "y"]) == ["a", "x", "b", "y"]


def test_interleave_accepts_empty_lists():
    assert interleave([], []) == []


def test_interleave_rejects_lists_of_different_length():
    with pytest.raises(ValueError, match="same length"):
        interleave(["a"], ["x", "y"])


def test_render_output_matches_the_example_from_the_task():
    values = interleave(
        ["FIRST STRING", "SECOND STRING", "THIRD STRING"],
        ["OTHER STRING", "ANOTHER STRING", "LAST STRING"],
    )

    assert render_output(values) == (
        "FIRST STRING, OTHER STRING, SECOND STRING, ANOTHER STRING, THIRD STRING, LAST STRING"
    )
