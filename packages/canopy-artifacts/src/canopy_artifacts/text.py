"""A version's text, which anchors resolve against, and the anchors themselves (DESIGN §38).

A version's text is what a reader sees of it, each run of whitespace one space and its ends trimmed, so a passage
reflowed is still found. For HTML it is the text the page shows, read from its markup with the stdlib's parser, never
the markup: a tag is no text, and the contents of `script`, `style`, `template`, and `title` are not shown. For
Markdown it is the source, until the store renders Markdown.

An anchor is a W3C Web Annotation `TextQuoteSelector` over that text: `exact`, the passage's words, and up to
`CONTEXT` characters of `prefix` and `suffix` either side, which tell two copies of it apart. It is found again by its
words: when they are there more than once, the copy whose sides match best wins, and the first of those that tie, as a
plan's comments are (the web UI's `plan-anchors.ts`). Words found nowhere are a passage gone, and never move to other
words.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Final, Literal, override

#: The most of the text either side of a passage an anchor keeps.
CONTEXT: Final = 32
#: The content types a version may have.
type ContentType = Literal["text/html", "text/markdown"]
#: Elements whose contents a page does not show.
_HIDDEN: Final = frozenset({"script", "style", "template", "title"})
#: Elements that sit inside a line of text, so their tags part no words. Any other tag starts or ends a block, or is
#: an element such as `br` or `img` that stands between words, so it parts the words either side.
_INLINE: Final = frozenset(
    {
        "a",
        "abbr",
        "b",
        "bdi",
        "bdo",
        "cite",
        "code",
        "data",
        "del",
        "dfn",
        "em",
        "font",
        "i",
        "ins",
        "kbd",
        "mark",
        "q",
        "s",
        "samp",
        "small",
        "span",
        "strong",
        "sub",
        "sup",
        "time",
        "u",
        "var",
    },
)


@dataclass(frozen=True)
class Anchor:
    """A passage, as its words and the text either side of them, each with its whitespace collapsed."""

    #: The passage's own words. Never empty.
    exact: str
    #: Up to `CONTEXT` characters before it, the nearest last.
    prefix: str = ""
    #: Up to `CONTEXT` characters after it, the nearest first.
    suffix: str = ""

    @classmethod
    def of(cls, exact: str, prefix: str = "", suffix: str = "") -> Anchor:
        """Make an anchor, each part's whitespace collapsed, as the text it resolves against is.

        Returns:
            The anchor.
        """
        return cls(collapse(exact), collapse(prefix), collapse(suffix))


def visible_text(content_type: ContentType, content: str) -> str:
    """Read the text a reader sees of `content`, whitespace collapsed.

    Returns:
        The text.
    """
    if content_type == "text/markdown":
        return collapse(content)
    parser = _Visible()
    parser.feed(content)
    parser.close()
    return collapse("".join(parser.parts))


def locate(text: str, anchor: Anchor) -> int | None:
    """Find where `anchor`'s passage starts in `text`, a version's text.

    Returns:
        The index of its first character, or None when its words are nowhere in `text`.
    """
    if not anchor.exact:
        return None
    prefix, suffix = anchor.prefix.rstrip(), anchor.suffix.lstrip()
    # Each copy is scored by index, never by slicing the text around it, so a passage found a million times in a long
    # version costs a million short comparisons rather than a million copies of the version.
    best: int | None = None
    best_score = -1
    at = text.find(anchor.exact)
    while at != -1:
        score = _common_suffix(text, at, prefix) + _common_prefix(text, at + len(anchor.exact), suffix)
        if score > best_score:
            best, best_score = at, score
            if score == len(prefix) + len(suffix):
                break
        at = text.find(anchor.exact, at + 1)
    return best


def collapse(text: str) -> str:
    """Make each run of whitespace in `text` one space, and trim its ends.

    Returns:
        The text.
    """
    return " ".join(text.split())


class _Visible(HTMLParser):
    """Collects the text of a page that is shown: its data outside hidden elements, words parted at block tags."""

    def __init__(self) -> None:
        """Start with no text."""
        super().__init__(convert_charrefs=True)
        #: The text so far, in pieces.
        self.parts: list[str] = []
        #: How many hidden elements the parser is inside.
        self._hidden = 0

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HIDDEN:
            self._hidden += 1
        elif tag not in _INLINE:
            self.parts.append(" ")

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN:
            self._hidden = max(0, self._hidden - 1)
        elif tag not in _INLINE:
            self.parts.append(" ")

    @override
    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def _common_suffix(text: str, end: int, want: str) -> int:
    """Count how many characters `text` before `end` ends with of what `want` ends with.

    Returns:
        The count, compared from the end back, the text's whitespace just before `end` aside.
    """
    i = end
    while i > 0 and text[i - 1].isspace():
        i -= 1
    n = 0
    while n < i and n < len(want) and text[i - 1 - n] == want[-1 - n]:
        n += 1
    return n


def _common_prefix(text: str, start: int, want: str) -> int:
    """Count how many characters `text` from `start` starts with of what `want` starts with.

    Returns:
        The count, the text's whitespace at `start` aside.
    """
    i = start
    while i < len(text) and text[i].isspace():
        i += 1
    n = 0
    while i + n < len(text) and n < len(want) and text[i + n] == want[n]:
        n += 1
    return n
