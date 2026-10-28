"""logfmt: one line of `key=value` pairs, the form the loop writes its output in when it goes to a file.

A value is written bare when it can be, and in double quotes otherwise: when it is empty, or holds a space, `=`, a
quote, a backslash, or a character that does not print. Inside quotes a quote and a backslash are escaped with a
backslash, and a newline, a tab, or another character that does not print is written as an escape, so a value never
breaks the line, whoever wrote it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Characters that make a printable value need quotes.
_QUOTED: Final = frozenset(' ="\\')
#: How a character is written inside quotes, for those `str.isprintable` passes that still need an escape.
_ESCAPES: Final = {'"': '\\"', "\\": "\\\\"}
#: How the characters that do not print and are common enough to read are written; the rest are `\uXXXX`.
_NAMED: Final = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
#: The last code point a `\uXXXX` escape holds; those after it are written `\UXXXXXXXX`.
_BMP_MAX: Final = 0xFFFF


def line(fields: Mapping[str, object]) -> str:
    """Write `fields` as one logfmt line, in their order. A None value is left out; a bool is `true` or `false`.

    Returns:
        The pairs, separated by single spaces, with no line break in them.
    """
    return " ".join(f"{key}={value(v)}" for key, v in fields.items() if v is not None)


def value(v: object) -> str:
    """Write one value as logfmt does: bare when nothing in it needs quotes, quoted and escaped otherwise.

    Returns:
        The value's text, quoted when it is empty or holds anything `_QUOTED` or unprintable.
    """
    text = ("true" if v else "false") if isinstance(v, bool) else str(v)
    if text and all(c.isprintable() and c not in _QUOTED for c in text):
        return text
    return '"' + "".join(_escaped(c) for c in text) + '"'


def _escaped(c: str) -> str:
    if c in _ESCAPES:
        return _ESCAPES[c]
    if c.isprintable():
        return c
    return _NAMED.get(c, f"\\u{ord(c):04x}" if ord(c) <= _BMP_MAX else f"\\U{ord(c):08x}")
