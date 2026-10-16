import pytest

from canopy.core import contract


@pytest.mark.parametrize(
    ("result_json", "expected"),
    [
        (None, {}),
        ("", {}),
        ("not json", {}),
        ('["a list"]', {}),
        ('"a string"', {}),
        ('{"summary": "did it", "prs": {"api": "https://x/1"}}', {"summary": "did it", "prs": {"api": "https://x/1"}}),
    ],
)
def test_stored_object_is_the_result_object_or_empty(result_json: str | None, expected: dict[str, object]) -> None:
    assert contract.stored_object(result_json) == expected


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"harness": "timed out", "summary": "did it"}, "timed out"),
        ({"harness": "", "summary": "did it"}, "did it"),
        ({"harness": None, "summary": "did it"}, "did it"),
        ({"summary": "did it"}, "did it"),
        ({"summary": 7}, "7"),
        ({"question": "which?"}, ""),
        ({}, ""),
    ],
)
def test_stored_note_is_the_harness_note_else_the_summary(result: dict[str, object], expected: str) -> None:
    assert contract.stored_note(result) == expected
