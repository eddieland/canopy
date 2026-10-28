"""What a memory's text may hold, and how it is shown (DESIGN §28, Bounds): between worker text and prompts."""

from __future__ import annotations

import re
from typing import Final

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from canopy.core.memory_text import (
    KEY_RE,
    TextRefused,
    check_key,
    check_text,
    hidden_char,
    looks_secret,
    normalized,
    quoted,
    visible,
)

# Characters a note may not hold, from each category: control but the line feed and tab, format (zero-width, bidi,
# tag), surrogate, private use, unassigned, and the line and paragraph separators.
HIDDEN: Final = [
    "\x00",
    "\r",
    "\x1b",
    "\u200b",
    "\u200d",
    "\u202e",
    "\u2066",
    "\ufeff",
    "\U000e0041",
    "\ue000",
    "\u2028",
]


@pytest.mark.parametrize("char", HIDDEN)
def test_a_hidden_character_is_refused_not_stripped(char: str) -> None:
    assert hidden_char(char)
    with pytest.raises(TextRefused, match="a character that hides text"):
        check_text(f"run the tests{char} twice", 400)


@pytest.mark.parametrize(
    "text",
    [
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "the key is AKIAIOSFODNN7EXAMPLE",
        "gho_16C7e42F292c6912E7710c838347Ae178B4a",
        "github_pat_11ABCDEFG0abcdefghijkl_mnop",
        "glpat-xxxxxxxxxxxxxxxxxxxx",
        "xoxb-1234567890-abcdefghij",
        "sk-proj-abcdefghijklmnopqrstuv",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "send Authorization: Bearer abcdefghijklmnop1234",
        "password = hunter2hunter2",
        "API_KEY: 8f3kZ2qLw9",
        "the token is aZ3kQ9vB2xLm7RtY5wPc",
    ],
)
def test_a_note_that_looks_like_a_secret_is_refused(text: str) -> None:
    assert looks_secret(text)
    with pytest.raises(TextRefused, match="looks like it holds a secret"):
        check_text(text, 400)


@pytest.mark.parametrize(
    "text",
    [
        "Reverted a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0, which broke the build.",
        "The failing test is in src/canopy/core/MemoryView2.py, not ui/src/components/MemoryPanel2.tsx.",
        "Set TOKEN=$GITHUB_TOKEN in the job; the password is in <the vault>.",
        "useMemoryReadout2Component renders twice; see https://github.com/acme/web/pull/584.",
        "bazel-out/k8-fastbuild/bin/api/server2 is stale after a rebase: run `bazel clean`.",
    ],
)
def test_ordinary_notes_pass(text: str) -> None:
    assert check_text(text, 400) == text


def test_a_text_keeps_its_line_breaks_and_tabs_and_shows_them_as_written() -> None:
    text = "Run the tests twice.\nEvidence: the first run\tfails on a cold cache."
    assert check_text(text, 400) == text
    assert quoted(text, "> ") == "> Run the tests twice.\n> Evidence: the first run\tfails on a cold cache."


def test_a_text_is_trimmed_and_bounded() -> None:
    assert check_text("  Run it twice.  ", 400) == "Run it twice."
    with pytest.raises(TextRefused, match="blank"):
        check_text("   ", 400)
    with pytest.raises(TextRefused, match="401 characters, over 400"):
        check_text("x" * 401, 400)
    with pytest.raises(TextRefused, match="not a string"):
        check_text(12, 400)


def test_repeats_compare_casefolded_with_whitespace_collapsed() -> None:
    assert normalized("Run  the\tTests") == normalized("run the tests")


@given(st.text())
def test_visible_text_holds_no_hidden_character_and_names_each(text: str) -> None:
    assume("<U+" not in text)
    shown = visible(text)
    assert not any(hidden_char(c) for c in shown)
    # Each name reads back as the character it stands for, so nothing is lost or changed.
    assert re.sub(r"<U\+([0-9A-F]{4,6})>", lambda m: chr(int(m.group(1), 16)), shown) == text


@given(st.text())
def test_quoted_text_puts_the_prefix_before_each_line_and_names_the_rest(text: str) -> None:
    assume("<U+" not in text)
    shown = quoted(text, "> ")
    assert all(line.startswith("> ") for line in shown.split("\n"))
    assert not any(hidden_char(c) and c not in "\n\t" for c in shown)
    lines = [line.removeprefix("> ") for line in shown.split("\n")]
    assert re.sub(r"<U\+([0-9A-F]{4,6})>", lambda m: chr(int(m.group(1), 16)), "\n".join(lines)) == text


@given(st.text(), st.sampled_from(HIDDEN), st.text())
def test_any_text_with_a_hidden_character_is_refused(before: str, char: str, after: str) -> None:
    with pytest.raises(TextRefused):
        check_text(f"x{before}{char}{after}x", 10_000)


@given(st.text(max_size=50))
def test_a_key_is_a_slug_or_refused(key: str) -> None:
    if KEY_RE.fullmatch(key) is None:
        with pytest.raises(TextRefused):
            check_key(key)
    else:
        assert check_key(key) == key
