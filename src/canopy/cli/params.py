"""Validated click parameter types for what the overseer passes in: ticket keys, reasons, slugs, cursors, and text.

Keys, slugs, and cursor ids reach branch names, paths, argv, and prompts, so they are checked before any command runs.
"""

from __future__ import annotations

import re
from typing import override

import click

from canopy.core import db, workspace
from canopy.runs import dispatch

KEY_RE = db.KEY_RE
REASON_RE = re.compile(r"[a-z][a-z0-9_]*")
CURSOR_VALUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}")
MAX_TEXT = 2000


def valid_key(value: str) -> bool:
    """Keys reach branch names, lease holders, paths, and argv (DESIGN §17)."""
    return KEY_RE.fullmatch(value) is not None


def truncate(value: str) -> str:
    """Bound free text the overseer writes to the journal."""
    return value if len(value) <= MAX_TEXT else value[: MAX_TEXT - 3] + "..."


class PatternType(click.ParamType[str, object]):
    """A string that must match a pattern: ticket keys and attention reasons."""

    def __init__(self, name: str, pattern: re.Pattern[str], what: str) -> None:
        """Name the type for help text, and say what `pattern` validates for error messages."""
        self.name = name
        self.pattern = pattern
        self.what = what

    @override
    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> str:
        if not isinstance(value, str) or not self.pattern.fullmatch(value):
            self.fail(f"invalid {self.what} {value!r}: must match {self.pattern.pattern}", param, ctx)
        return value


class CursorType(click.ParamType[tuple[str, str], object]):
    """A `--cursor NAME=ID` pair; the id is later rendered into prompts, so it is kept short and plain."""

    name = "NAME=ID"

    @override
    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> tuple[str, str]:
        cursor_name, sep, cursor_id = str(value).partition("=")
        if not sep or cursor_name not in db.CURSOR_COLUMNS:
            self.fail(f"cursor must be NAME=ID with NAME one of {', '.join(db.CURSOR_COLUMNS)}", param, ctx)
        if not CURSOR_VALUE_RE.fullmatch(cursor_id):
            self.fail(f"invalid cursor id {cursor_id!r}", param, ctx)
        return cursor_name, cursor_id


class TextType(click.ParamType[str, object]):
    """Free text the overseer writes into the journal: stripped, non-empty, bounded."""

    name = "TEXT"

    @override
    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> str:
        text = str(value).strip()
        if not text:
            self.fail("must not be empty", param, ctx)
        return truncate(text)


TICKET_KEY = PatternType("KEY", KEY_RE, "ticket key")
REASON = PatternType("REASON", REASON_RE, "reason")
SLUG = PatternType("SLUG", dispatch.SLUG_RE, "slug")
REPO = PatternType("NAME", workspace.REPO_NAME_RE, "repository name")
