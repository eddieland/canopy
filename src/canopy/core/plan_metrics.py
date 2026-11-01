"""How long a plan is, measured from its Markdown (DESIGN §25), for the Plans report.

Reads only: a plan's text in, its measurements out. `lines` estimates how far the operator scrolls through the plan in
the web UI's plan editor: each block's rendered text, wrapped at the editor's width and weighted by how tall the editor
draws it. The weights were fitted to the heights the editor drew for 110 Markdown files (the repository's own docs and
the mock's plans); held out, the estimate came within 6% of the drawn height for nine files in ten. A diagram counts a
fixed `DIAGRAM_LINES`, since how tall it draws depends on what it draws.

The scan is line by line, not a full CommonMark parser: fenced code, headings, lists, tables, quotes, rules, and
paragraphs, which is what a planner writes. Whatever it does not recognize counts as a paragraph.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

#: The model's version, kept with each plan's cached measurements (`plan_lengths`): raise it when a change to the model
#: below would measure a plan differently, and every plan is measured again.
VERSION = 1
#: The characters of body text the plan editor fits on a line, at its widest.
LINE_CHARS = 100
#: The characters of a table's row the editor fits on a line: its smaller type takes more.
TABLE_CHARS = 120
#: How many of the editor's lines a diagram counts, whatever it draws.
DIAGRAM_LINES = 15

type _Kind = Literal["para", "quote", "item", "h12", "h34", "code", "diagram", "table", "rule"]

# How tall each kind of block draws, in the editor's lines, per line of its wrapped text, and once per block: fitted to
# the editor's drawn heights (module docstring). A heading is larger type with space above it; a code block is smaller
# type in a padded box; an item carries its list's gap.
_PER_LINE: dict[_Kind, float] = {
    "para": 1.05,
    "quote": 1.05,
    "item": 1.15,
    "h12": 2.0,
    "h34": 1.75,
    "code": 0.85,
    "table": 1.1,
}
_PER_BLOCK: dict[_Kind, float] = {"code": 1.5, "diagram": DIAGRAM_LINES}


@dataclass(frozen=True)
class Metrics:
    """How long a plan is, and how much of it is not prose."""

    #: Its words outside code blocks and diagrams, tables' cells included.
    words: int
    #: How many of the plan editor's lines it fills, estimated: what the operator scrolls through.
    lines: int
    #: Its fenced code blocks, diagrams aside.
    code_blocks: int
    tables: int
    #: Its Mermaid diagrams.
    diagrams: int


def measure(text: str) -> Metrics:
    """Measure the plan `text`.

    Returns:
        Its words, its estimated lines in the plan editor, and its code blocks, tables, and diagrams.
    """
    blocks = _parse(text)
    lines = 0.0
    words = 0
    for block in blocks:
        wrapped = sum(_wrap(t, _width(block)) for t in block.texts)
        lines += _PER_LINE.get(block.kind, 0.0) * wrapped + _PER_BLOCK.get(block.kind, 0.0)
        if block.kind not in {"code", "diagram"}:
            words += sum(len(t.split()) for t in block.texts)
    return Metrics(
        words=words,
        lines=round(lines),
        code_blocks=sum(1 for b in blocks if b.kind == "code"),
        tables=sum(1 for b in blocks if b.kind == "table"),
        diagrams=sum(1 for b in blocks if b.kind == "diagram"),
    )


# The characters a block's text fits on a line: a top heading's larger type fits fewer, and an item or a quote is
# indented, an item three characters more for each list it is nested in.
def _width(block: _Block) -> int:
    match block.kind:
        case "table":
            return TABLE_CHARS
        case "h12":
            return LINE_CHARS * 4 // 5
        case "item":
            return LINE_CHARS - 3 - 3 * block.depth
        case "quote":
            return LINE_CHARS - 3
        case _:
            return LINE_CHARS


_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*([\w+-]*)")
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_ITEM = re.compile(r"^(\s*)(?:[-*+]|\d{1,9}[.)])\s+(?:\[[ xX]\]\s+)?(.*)$")
_RULE = re.compile(r"^ {0,3}([-*_])(?:\s*\1){2,}\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MARKS = re.compile(r"\*\*|__|\*|_|`|~~")


@dataclass(frozen=True)
class _Block:
    """A block of a plan's Markdown, and its text as the editor shows it."""

    kind: _Kind
    #: A paragraph's or heading's text, an item's, each line of a code block, or each row of a table, its cells joined.
    texts: Sequence[str]
    #: How deep an item's list is nested; 0 for any other block.
    depth: int = 0


def _parse(text: str) -> list[_Block]:
    lines = text.splitlines()
    blocks: list[_Block] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif fence := _FENCE.match(line):
            i = _fenced(lines, i, fence, blocks)
        elif heading := _HEADING.match(line):
            blocks.append(_Block("h12" if len(heading.group(1)) <= 2 else "h34", [_shown(heading.group(2))]))  # noqa: PLR2004
            i += 1
        elif _RULE.match(line):
            blocks.append(_Block("rule", []))
            i += 1
        elif line.lstrip().startswith("|") and i + 1 < len(lines) and _TABLE_SEPARATOR.match(lines[i + 1]):
            i = _table(lines, i, blocks)
        elif line.lstrip().startswith(">"):
            body: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                body.append(lines[i].lstrip()[1:].strip())
                i += 1
            blocks.append(_Block("quote", [_shown(" ".join(body))]))
        elif item := _ITEM.match(line):
            i = _item(lines, i, item, blocks)
        else:
            i = _paragraph(lines, i, blocks)
    return blocks


# A fenced block, from its opening fence to its closing one or the end: a diagram when its language is Mermaid.
def _fenced(lines: Sequence[str], i: int, fence: re.Match[str], blocks: list[_Block]) -> int:
    mark = fence.group(1)
    body: list[str] = []
    i += 1
    while i < len(lines) and not lines[i].strip().startswith(mark):
        body.append(lines[i])
        i += 1
    blocks.append(_Block("diagram" if fence.group(2).lower() == "mermaid" else "code", body or [""]))
    return i + 1


# A table: its head, then each row that starts with a pipe; the separator under the head draws nothing.
def _table(lines: Sequence[str], i: int, blocks: list[_Block]) -> int:
    rows = [lines[i]]
    i += 2
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        rows.append(lines[i])
        i += 1
    blocks.append(_Block("table", [" ".join(_shown(c) for c in r.strip().strip("|").split("|")) for r in rows]))
    return i


# A list item, with the lines that continue it: up to a blank line or the next block's start.
def _item(lines: Sequence[str], i: int, item: re.Match[str], blocks: list[_Block]) -> int:
    body = [item.group(2)]
    i += 1
    while i < len(lines) and lines[i].strip() and not _starts_block(lines[i]):
        body.append(lines[i].strip())
        i += 1
    depth = len(item.group(1).expandtabs(4)) // 2
    blocks.append(_Block("item", [_shown(" ".join(body))], depth=depth))
    return i


# A paragraph: its lines, joined as the editor joins them, up to a blank line or the next block's start.
def _paragraph(lines: Sequence[str], i: int, blocks: list[_Block]) -> int:
    body = [lines[i].strip()]
    i += 1
    while i < len(lines) and lines[i].strip() and not _starts_block(lines[i]) and not _RULE.match(lines[i]):
        body.append(lines[i].strip())
        i += 1
    blocks.append(_Block("para", [_shown(" ".join(body))]))
    return i


def _starts_block(line: str) -> bool:
    return bool(_ITEM.match(line) or _FENCE.match(line) or _HEADING.match(line)) or line.lstrip().startswith(("|", ">"))


# Text as the editor shows it: a link's words without its address, and no emphasis or code marks.
def _shown(text: str) -> str:
    return _MARKS.sub("", _LINK.sub(r"\1", text)).strip()


def _wrap(text: str, width: int) -> int:
    return max(1, math.ceil(len(text) / width))
