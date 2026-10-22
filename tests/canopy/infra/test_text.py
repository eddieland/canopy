"""`text.quoted`: untrusted text as a Markdown quote that no line of it can leave."""

from hypothesis import given
from hypothesis import strategies as st

from canopy.infra import text


def test_quoted_prefixes_every_line_and_drops_control_characters() -> None:
    assert text.quoted("one\r\n## two\n\nthree\x1b[2J") == "> one\n> ## two\n> \n> three [2J"


def test_quoted_empty_text_is_one_empty_quote_line() -> None:
    assert text.quoted("") == "> "


@given(st.text())
def test_no_line_of_quoted_text_leaves_the_quote(value: str) -> None:
    assert all(line.startswith("> ") for line in text.quoted(value).split("\n"))
