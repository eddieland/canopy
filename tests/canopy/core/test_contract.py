import pytest
from pydantic import BaseModel

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


class _Result(BaseModel):
    status: str
    answers: list[dict[str, str]] = []


@pytest.mark.parametrize(
    ("line", "answers"),
    [
        # Issue 2245: the array was never closed, and the line ended `}}`.
        ('{"status": "blocked", "answers": [{"reason": "a } in [text"}}', [{"reason": "a } in [text"}]),
        ('{"status": "blocked", "answers": [{"reason": "an escaped \\" quote"}', [{"reason": 'an escaped " quote'}]),
        ('{"status": "blocked", "answers": [{"reason": "r"}]', [{"reason": "r"}]),
        ('{"status": "blocked", "answers": [{"reason": "r"}]}}', [{"reason": "r"}]),
        ('{"status": "blocked", "answers": []]}', []),
    ],
)
def test_a_result_line_wrong_only_in_its_closing_brackets_is_repaired(line: str, answers: list[dict[str, str]]) -> None:
    text = f"working\n{line}\n[plugin] a notice\n"
    assert contract.last_line(_Result, text) == _Result(status="blocked", answers=answers)
    assert contract.repaired(text)


@pytest.mark.parametrize(
    "line",
    [
        '{"status": "blocked", "answers": [{"reason": "cut sho',
        '{"status": "blocked", "answers": [{"reason": "cut short"',
        '{"status": "blocked", "answers": [{"reason": "r"}, "more": 1}',
        '{"status": "blocked",, "answers": []}',
        '{"status": "blocked", "answers": [[[[{"reason": "r"}',
        '{"answers": [}',
    ],
)
def test_a_result_line_wrong_in_more_than_its_closing_is_no_result(line: str) -> None:
    assert contract.last_line(_Result, line) is None


def test_a_valid_result_line_is_not_repaired() -> None:
    text = '{"status": "done"}'
    assert contract.last_line(_Result, text) == _Result(status="done")
    assert not contract.repaired(text)
    assert not contract.repaired("no result")
    assert not contract.repaired('{"status": "blocked",, "answers": []}')
