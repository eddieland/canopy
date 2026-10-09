"""Validated click parameter types for what the overseer passes in: ticket keys, reasons, slugs, cursors, and text.

Keys, slugs, and cursor ids reach branch names, paths, argv, and prompts, so they are checked before any command runs.
"""

from __future__ import annotations

import re
from typing import override

import click

from canopy.core import config, contract, db
from canopy.runs import dispatch

KEY_RE = dispatch.KEY_RE
REASON_RE = re.compile(r"[a-z][a-z0-9_]*")
CURSOR_VALUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}")
# A review cursor is a time, the one form every kind of review feedback shares (DESIGN §7, D096).
REVIEW_CURSOR_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
MAX_TEXT = 2000
MAX_PR_URL = 300


def valid_key(value: str) -> bool:
    """Keys reach branch names, lease holders, paths, and argv (DESIGN §17)."""
    return KEY_RE.fullmatch(value) is not None


def valid_review_cursor(value: str) -> bool:
    """A review cursor names a real moment in one fixed form, so cursors compare as strings (DESIGN §7)."""
    if REVIEW_CURSOR_RE.fullmatch(value) is None:
        return False
    try:
        db.parse_time(value)
    except ValueError:
        return False
    return True


def plain_pr_url(value: str) -> bool:
    """A PR's URL as the overseer passes it: a plain https:// URL, at most 300 characters (DESIGN §21)."""
    return contract.plain_url(value, MAX_PR_URL)


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
        # A message cursor is a journal message id (DESIGN §22).
        if cursor_name == "message" and not (cursor_id.isascii() and cursor_id.isdigit()):
            self.fail(f"a message cursor is a message id, a number; got {cursor_id!r}", param, ctx)
        if cursor_name == "review" and not valid_review_cursor(cursor_id):
            self.fail(
                f"a review cursor is the newest handled item's time in UTC, as YYYY-MM-DDTHH:MM:SSZ; got {cursor_id!r}",
                param,
                ctx,
            )
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
REPO = PatternType("NAME", config.REPO_NAME_RE, "repository name")
CHORE = PatternType("NAME", config.CHORE_NAME_RE, "chore name")
# A tracker's comment id, as a cursor id is: it reaches the worker's prompt and the journal.
COMMENT_ID = PatternType("COMMENT_ID", CURSOR_VALUE_RE, "comment id")
