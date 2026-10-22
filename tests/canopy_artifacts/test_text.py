"""A version's visible text, and anchors found again by their words in it (DESIGN §38, Anchors by words)."""

from __future__ import annotations

import html

import pytest
from canopy_artifacts.text import CONTEXT, Anchor, collapse, locate, visible_text
from hypothesis import assume, given
from hypothesis import strategies as st

#: A word: letters, digits, punctuation, and symbols, `<` and `&` among them, and no whitespace.
WORDS = st.text(st.characters(categories=["L", "N", "P", "S"]), min_size=1, max_size=12)
#: Text whose whitespace is collapsed, as a version's is.
TEXTS = st.lists(WORDS, min_size=1, max_size=40).map(" ".join)


@pytest.mark.parametrize(
    ("page", "text"),
    [
        ("<p>Hello <b>big</b> world.</p><p>Second</p>", "Hello big world. Second"),
        ("<html><head><title>Hidden</title><style>p { x: 1 }</style></head><body>Shown</body></html>", "Shown"),
        ("<div>one<br>two</div><script>alert('no')</script><template><p>later</p></template>", "one two"),
        ("<li>a&amp;b</li><li>&lt;c&gt;</li><!-- a comment -->", "a&b <c>"),
        ("<p>in\n   a\tline</p>", "in a line"),
        ("<p>word<span>s</span> stay whole</p>", "words stay whole"),
    ],
)
def test_html_text_is_what_the_page_shows_never_its_markup(page: str, text: str) -> None:
    assert visible_text("text/html", page) == text


def test_markdown_text_is_its_source_whitespace_collapsed() -> None:
    assert visible_text("text/markdown", "# Plan\n\nShip  the\nthing.\n") == "# Plan Ship the thing."


def test_a_passage_is_found_by_its_words_and_the_best_matching_copy_wins() -> None:
    text = "the cache is slow here. Later, the cache is slow there."
    second = Anchor.of("the cache is slow", prefix="here. Later,", suffix="there.")
    assert locate(text, second) == text.rindex("the cache is slow")
    # With no sides to tell them apart, the first copy.
    assert locate(text, Anchor.of("the cache is slow")) == 0
    # Sides that match nothing still find the words.
    assert locate(text, Anchor.of("Later", prefix="zzz", suffix="qqq")) == text.index("Later")


def test_words_found_nowhere_are_gone_and_never_move() -> None:
    assert locate("the cache is fast", Anchor.of("the cache is slow", suffix="")) is None
    assert locate("anything", Anchor("")) is None


def test_an_anchor_collapses_its_whitespace_as_the_text_does() -> None:
    assert Anchor.of("  the\n cache ", "a  b ", "\tc") == Anchor("the cache", "a b", "c")
    assert locate(visible_text("text/markdown", "the\n\ncache"), Anchor.of("the   cache")) == 0


@given(text=TEXTS, data=st.data())
def test_any_passage_cut_from_a_text_is_found_there(text: str, data: st.DataObject) -> None:
    start = data.draw(st.integers(0, len(text) - 1))
    end = data.draw(st.integers(start + 1, len(text)))
    assume(text[start:end].strip())
    anchor = Anchor.of(text[start:end], text[max(0, start - CONTEXT) : start], text[end : end + CONTEXT])
    found = locate(text, anchor)
    assert found is not None
    assert text[found:].startswith(anchor.exact)
    if text.count(anchor.exact) == 1:
        cut = text[start:end]
        assert found == start + len(cut) - len(cut.lstrip())


@given(words=st.lists(WORDS, min_size=1, max_size=20), data=st.data())
def test_html_text_holds_the_words_and_no_markup(words: list[str], data: st.DataObject) -> None:
    tags = data.draw(st.lists(st.sampled_from(["p", "div", "b", "span", "li", "h2", "td"]), min_size=len(words)))
    hidden = data.draw(WORDS.filter(lambda w: "</" not in w))
    page = "".join(f"<{tag}>{html.escape(word)}</{tag}> " for tag, word in zip(tags, words, strict=False))
    page += f"<script>{hidden}</script><style>{hidden}</style>"
    assert visible_text("text/html", page) == " ".join(words)


@given(words=st.lists(WORDS, min_size=1, max_size=20), gaps=st.lists(st.sampled_from([" ", "\n", "\t  ", "\n\n"])))
def test_a_reflowed_text_reads_the_same(words: list[str], gaps: list[str]) -> None:
    reflowed = "".join(word + (gaps[i % len(gaps)] if gaps else " ") for i, word in enumerate(words))
    assert visible_text("text/markdown", reflowed) == collapse(" ".join(words))


def test_a_passage_found_everywhere_in_the_longest_version_is_scored_without_copying_the_text() -> None:
    # A version as long as the store takes, and a one-letter passage found at every other character: slicing the text
    # around each copy, as `locate` once did, would copy it a million times over.
    text = "e " * 999_999 + "e z"
    assert locate(text, Anchor.of("e", suffix="z")) == len(text) - 3
    assert locate(text, Anchor.of("e")) == 0


@given(text=TEXTS, exact=WORDS, prefix=st.text(max_size=CONTEXT), suffix=st.text(max_size=CONTEXT))
def test_the_copy_chosen_is_the_one_whose_sides_match_best_and_the_first_of_a_tie(
    text: str,
    exact: str,
    prefix: str,
    suffix: str,
) -> None:
    anchor = Anchor.of(exact, prefix, suffix)
    copies = [at for at in range(len(text)) if text.startswith(anchor.exact, at)]
    found = locate(text, anchor)
    if not copies:
        assert found is None
        return
    scores = [_score(text, at, anchor) for at in copies]
    assert found == copies[scores.index(max(scores))]


def _score(text: str, at: int, anchor: Anchor) -> int:
    """Score a copy as the plan editor does, by slicing: the characters its sides share with the anchor's."""
    before, want = text[:at].rstrip(), anchor.prefix.rstrip()
    after, wanted = text[at + len(anchor.exact) :].lstrip(), anchor.suffix.lstrip()
    common = 0
    while common < min(len(before), len(want)) and before[-1 - common] == want[-1 - common]:
        common += 1
    ahead = 0
    while ahead < min(len(after), len(wanted)) and after[ahead] == wanted[ahead]:
        ahead += 1
    return common + ahead
