"""The outbox's text helpers: what a notification event's fields hold of agent-written text (DESIGN §20)."""

import pytest

from canopy.core import outbox


@pytest.mark.parametrize(
    ("text", "limit", "lines"),
    [
        ("One.\n\n  Two   words.\n", 100, ["One.", "Two words."]),
        # The line that passes the limit is cut to what is left, ending in `...`.
        ("One.\nTwo words.", 10, ["One.", "Two..."]),
        # With no more than `...` left, it is left out, and nothing after it is kept.
        ("One.\nTwo words.\nThree.", 7, ["One."]),
        ("", 10, []),
    ],
)
def test_cut_lines_keeps_whole_lines_until_the_limit(text: str, limit: int, lines: list[str]) -> None:
    """Each line keeps its words, and the lines together keep to the limit."""
    assert outbox.cut_lines(text, limit) == lines
    assert sum(len(line) for line in lines) <= limit
