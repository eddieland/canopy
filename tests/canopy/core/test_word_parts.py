"""A name written as one word, split into its parts, and a text written with them."""

from __future__ import annotations

import pytest

from canopy.core import word_parts


@pytest.mark.parametrize(
    ("word", "parts"),
    [
        ("ValidationManager", ["Validation", "Manager"]),
        ("validationManager", ["validation", "Manager"]),
        ("validation_manager", ["validation", "manager"]),
        ("__VALIDATION_MANAGER", ["VALIDATION", "MANAGER"]),
        ("HTTPServerError", ["HTTP", "Server", "Error"]),
        ("parseXMLFile", ["parse", "XML", "File"]),
        # A digit stays with the letters before it.
        ("utf8Decoder", ["utf8", "Decoder"]),
        ("HTTP2Server", ["HTTP2", "Server"]),
        ("sha256sum", ["sha256sum"]),
        ("4ae05f5", ["4ae05f5"]),
        ("manager", ["manager"]),
        ("caféBar", ["caféBar"]),
        ("_", []),
    ],
)
def test_a_word_splits_at_each_underscore_and_where_its_case_changes(word: str, parts: list[str]) -> None:
    assert word_parts.parts(word) == parts


def test_a_name_too_long_or_of_too_many_parts_is_left_whole() -> None:
    encoded = "aGVsbG8gd29ybGQhIGhlbGxvIHdvcmxkIQ"
    long = "Ab" * word_parts.MAX_NAME

    assert word_parts.parts(encoded) == [encoded]
    assert word_parts.parts(long) == [long]
    assert word_parts.spread(f"{encoded} {long}") == f"{encoded} {long}"


def test_a_text_is_written_with_each_names_parts_after_it() -> None:
    text = "class ValidationManager(Base): parseXMLFile(the_path) # plain words, and sha256sum"

    assert word_parts.spread(text) == (
        "class ValidationManager Validation Manager(Base): parseXMLFile parse XML File(the_path)"
        " # plain words, and sha256sum"
    )
    assert list(word_parts.compounds(text)) == [
        ("ValidationManager", ["Validation", "Manager"]),
        ("parseXMLFile", ["parse", "XML", "File"]),
    ]


def test_a_long_run_with_no_change_of_case_is_read_once() -> None:
    """A run a run wrote cannot make the read slow: it would not end in time were each of its letters tried."""
    text = "a" * 2_000_000

    assert word_parts.spread(text) == text
