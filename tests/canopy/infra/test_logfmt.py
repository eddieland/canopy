"""`logfmt`: values bare when they can be, quoted and escaped when not, and never a line break."""

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from canopy.infra import logfmt

#: A quoted value's escapes, as `_read` takes them back.
_ESCAPE = re.compile(r"\\(U[0-9a-f]{8}|u[0-9a-f]{4}|.)")
_NAMED = {"n": "\n", "r": "\r", "t": "\t"}


def test_a_line_holds_the_fields_in_order_and_leaves_out_none() -> None:
    fields = {"time": "2026-10-21T01:06:32+00:00", "msg": "tick ended", "tick": 1, "paused": None, "dry_run": False}
    assert logfmt.line(fields) == 'time=2026-10-21T01:06:32+00:00 msg="tick ended" tick=1 dry_run=false'


@pytest.mark.parametrize(
    ("value", "written"),
    [
        ("ok", "ok"),
        ("dispatch:implement", "dispatch:implement"),
        ("https://example.test/pr/3", "https://example.test/pr/3"),
        ("", '""'),
        ("a b", '"a b"'),
        ("ok=1", '"ok=1"'),
        ('say "hi"', r'"say \"hi\""'),
        (r"C:\dir", r'"C:\\dir"'),
        ("two\nlines", r'"two\nlines"'),
        ("tab\there", r'"tab\there"'),
        ("bell\x07", r'"bell\u0007"'),
        ("café · ok", '"café · ok"'),
        (True, "true"),
        (2.5, "2.5"),
    ],
)
def test_a_value_is_quoted_only_when_it_must_be(value: object, written: str) -> None:
    assert logfmt.value(value) == written


@given(st.text())
def test_any_text_stays_on_one_line_and_reads_back(text: str) -> None:
    written = logfmt.value(text)
    assert len(f"msg={written}".splitlines()) == 1
    assert _read(written) == text


def _read(written: str) -> str:
    """A value as a logfmt reader takes it back."""
    if not written.startswith('"'):
        return written
    return _ESCAPE.sub(_unescape, written[1:-1])


def _unescape(match: re.Match[str]) -> str:
    code = match.group(1)
    if code[0] in "uU" and len(code) > 1:
        return chr(int(code[1:], 16))
    return _NAMED.get(code, code)
