"""Validated click parameter types for what the overseer passes in: ticket keys, reasons, slugs, cursors, and text.

Keys, slugs, and cursor ids reach branch names, paths, argv, and prompts, so they are checked before any command runs.
Repository and chore names also complete in the shell, from the config of the workspace the shell is in.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import override

import click
from click.shell_completion import CompletionItem

from canopy.chores import install
from canopy.core import config, contract, db, workspace
from canopy.runs import dispatch

KEY_RE = dispatch.KEY_RE
REASON_RE = re.compile(r"[a-z][a-z0-9_]*")
CURSOR_VALUE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}")
# A review cursor is a time, the one form every kind of review feedback shares (DESIGN §7).
REVIEW_CURSOR_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
MAX_TEXT = 2000
# A ticket's title is a name, shown beside its key and in its runs' session titles (DESIGN §13).
MAX_TITLE = 80
MAX_PR_URL = 300


def valid_key(value: str) -> bool:
    """Keys reach branch names, lease holders, paths, and argv (DESIGN §17).

    Returns:
        True when `value` matches `KEY_RE` in full.
    """
    return KEY_RE.fullmatch(value) is not None


def valid_review_cursor(value: str) -> bool:
    """A review cursor names a real moment in one fixed form, so cursors compare as strings (DESIGN §7).

    Returns:
        True when `value` is in the form `YYYY-MM-DDTHH:MM:SSZ` and names a real time.
    """
    if REVIEW_CURSOR_RE.fullmatch(value) is None:
        return False
    try:
        db.parse_time(value)
    except ValueError:
        return False
    return True


def truncate(value: str) -> str:
    """Bound free text the overseer writes to the journal.

    Returns:
        `value` unchanged when it fits in `MAX_TEXT`, else cut to it and ended with "...".
    """
    return value if len(value) <= MAX_TEXT else value[: MAX_TEXT - 3] + "..."


class PatternType(click.ParamType[str, object]):
    """A string that must match a pattern: ticket keys and attention reasons."""

    def __init__(
        self, name: str, pattern: re.Pattern[str], what: str, names: Callable[[], Iterable[str]] | None = None
    ) -> None:
        """Name the type for help text, and say what `pattern` validates for error messages.

        `names`, when given, lists the values the shell offers to complete.
        """
        self.name = name
        self.pattern = pattern
        self.what = what
        self.names = names

    @override
    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> str:
        if not isinstance(value, str) or not self.pattern.fullmatch(value):
            self.fail(f"invalid {self.what} {value!r}: must match {self.pattern.pattern}", param, ctx)
        return value

    @override
    def shell_complete(self, ctx: click.Context, param: click.Parameter, incomplete: str) -> list[CompletionItem]:
        if self.names is None:
            return []
        return [CompletionItem(name) for name in self.names() if name.startswith(incomplete)]


class PrUrlType(click.ParamType[str, object]):
    """A PR's URL as the overseer passes it: a plain https:// URL, at most `MAX_PR_URL` characters (DESIGN §21).

    It reaches the journal's `pr` column, the state block, and the web UI's links.
    """

    name = "URL"

    @override
    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> str:
        if not isinstance(value, str) or not contract.plain_url(value, MAX_PR_URL):
            self.fail(f"must be a plain https:// URL of at most {MAX_PR_URL} characters", param, ctx)
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


class TitleType(click.ParamType[str, object]):
    """A ticket's title: one line, control characters dropped, whitespace collapsed, non-empty, and cut."""

    name = "TITLE"

    @override
    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> str:
        title = " ".join("".join(c if c.isprintable() else " " for c in str(value)).split())
        if not title:
            self.fail("must not be empty", param, ctx)
        return title if len(title) <= MAX_TITLE else title[: MAX_TITLE - 3] + "..."


def repo_names() -> list[str]:
    """Complete a repository's name from the map of the workspace the shell is in.

    Returns:
        Each repository's name, or none outside a workspace or when its map does not load: completion never fails.
    """
    try:
        return [repo.name for repo in workspace.find(Path.cwd()).repos]
    except (config.ConfigError, OSError):
        return []


def chore_names() -> list[str]:
    """Complete a chore's name from the config of the workspace the shell is in.

    Returns:
        Each chore's name, or none outside a workspace or when the config does not load: completion never fails.
    """
    try:
        root = workspace.find_root(Path.cwd())
        return [] if root is None else sorted(config.load(root).chores)
    except (config.ConfigError, OSError):
        return []


TICKET_KEY = PatternType("KEY", KEY_RE, "ticket key")
REASON = PatternType("REASON", REASON_RE, "reason")
SLUG = PatternType("SLUG", dispatch.SLUG_RE, "slug")
REPO = PatternType("NAME", config.REPO_NAME_RE, "repository name", repo_names)
CHORE = PatternType("NAME", config.CHORE_NAME_RE, "chore name", chore_names)
# One of the example chores canopy ships, which `canopy chore install` sets up.
EXAMPLE_CHORE = PatternType("NAME", config.CHORE_NAME_RE, "chore name", install.available)
PR_URL = PrUrlType()
# A tracker's comment id, as a cursor id is: it reaches the worker's prompt and the journal.
COMMENT_ID = PatternType("COMMENT_ID", CURSOR_VALUE_RE, "comment id")
