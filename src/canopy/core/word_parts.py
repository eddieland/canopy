"""The parts of a name written as one word, so a search finds `ValidationManager` by `validation manager`.

The index of sessions' words splits text where a person's prose breaks, at spaces and punctuation, so
`validation-manager` and `validation_manager` are already two words each, and `ValidationManager` is one. This module
splits such a name where its case changes (`parts`), and writes a text with each one's parts after it (`spread`), which
is what the index is given: the name is then found whole and by its parts, next to each other. A digit stays with the
letters before it, so a hash or a version is not cut into pieces, and a name too long or of too many parts is left
whole: it is more likely encoded data than a name, and its pieces would fill the index with words nobody searches for.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

#: How long a name is split up to, in characters, and into how many parts at most.
MAX_NAME: Final = 64
MAX_PARTS: Final = 8
#: A run of ASCII letters and digits whose case changes inside it: tried only where a run starts, so a long run with no
#: change is read once.
_COMPOUND: Final = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]*(?:[a-z0-9][A-Z]|[A-Z][A-Z][a-z])[A-Za-z0-9]*")
#: One part of such a run: capitals before a capitalized word (`XML` of `XMLFile`), a word, or capitals at its end.
_PART: Final = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+[0-9]*")


def parts(word: str) -> list[str]:
    """Split `word`, one word of a query or a text, at each `_` and where its case changes.

    Returns:
        Its parts in order: `["Validation", "Manager"]` of `ValidationManager`, `["parse", "XML", "File"]` of
        `parseXMLFile`. A piece that is not ASCII letters and digits, or is too long or of too many parts to be a
        name, is one part.
    """
    return [part for piece in word.split("_") if piece for part in _cased(piece)]


def compounds(text: str) -> Iterator[tuple[str, list[str]]]:
    """Find each name in `text` that splits into parts, in order, as often as it is written.

    Yields:
        The name as written, and its parts.
    """
    for found in _COMPOUND.finditer(text):
        split = _cased(found.group())
        if len(split) > 1:
            yield found.group(), split


def spread(text: str) -> str:
    """Write `text` with the parts of each name that splits after it, as the index is given it.

    Returns:
        The text, `ValidationManager` as `ValidationManager Validation Manager`.
    """
    return _COMPOUND.sub(_with_parts, text)


def _with_parts(found: re.Match[str]) -> str:
    split = _cased(found.group())
    return found.group() if len(split) < 2 else f"{found.group()} {' '.join(split)}"  # noqa: PLR2004


# The parts of `piece`, which holds no `_`, by its case.
def _cased(piece: str) -> list[str]:
    if len(piece) > MAX_NAME or not (piece.isascii() and piece.isalnum()):
        return [piece]
    split = _PART.findall(piece)
    return split if len(split) <= MAX_PARTS else [piece]
