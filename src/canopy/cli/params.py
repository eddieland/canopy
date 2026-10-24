"""Validated click parameter types for what the overseer passes in, and how a command does one of its verbs.

Keys, slugs, and cursor ids reach branch names, paths, argv, and prompts, so they are checked before any command runs,
by the same checks the verbs' requests make (`loop.tools`). Repository and chore names also complete in the shell, from
the config of the workspace the shell is in.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, override

import click
from click.shell_completion import CompletionItem
from pydantic import ValidationError

from canopy.chores import install
from canopy.cli.common import CliError, open_context
from canopy.core import config, git_tools, workspace
from canopy.loop import tools
from canopy.loop.tools import (
    CURSOR_VALUE_RE,
    KEY_RE,
    MAX_PR_URL,
    MAX_TEXT,
    MAX_TITLE,
    REASON_RE,
    truncate,
    valid_key,
)
from canopy.runs import dispatch

if TYPE_CHECKING:
    from pydantic import BaseModel

    from canopy.core.context import Context

__all__ = [
    "CURSOR_VALUE_RE",
    "KEY_RE",
    "MAX_PR_URL",
    "MAX_TEXT",
    "MAX_TITLE",
    "REASON_RE",
    "truncate",
    "valid_key",
]


def verb[R: BaseModel](
    click_ctx: click.Context,
    do: Callable[[Context, R], tools.Outcome[tools.Result]],
    request: type[R],
    **fields: object,
) -> int:
    """Do one of the overseer's verbs (`loop.tools`) as its command: build its request, do it, and print what it says.

    Returns:
        0, once it has printed what the verb said.

    Raises:
        click.UsageError: The request does not validate: misuse, exit 2.
        CliError: The verb refused: exit 1.
    """
    built = validated(click_ctx, request, **fields)
    ctx = open_context(click_ctx)
    try:
        said = do(ctx, built)
    except tools.Refused as e:
        raise CliError(str(e)) from None
    click.echo(said.text)
    return 0


def validated[R: BaseModel](click_ctx: click.Context, request: type[R], **fields: object) -> R:
    """Build one of the overseer's requests from a command's parameters.

    Returns:
        The request, validated.

    Raises:
        click.UsageError: It does not validate, saying why as its tool would.
    """
    try:
        return request.model_validate(fields)
    except ValidationError as e:
        raise click.UsageError(tools.explain(e), click_ctx) from None


class PatternType(click.ParamType[str, object]):
    """A string that must match a pattern: ticket keys and attention reasons."""

    def __init__(
        self,
        name: str,
        pattern: re.Pattern[str],
        what: str,
        names: Callable[[], Iterable[str]] | None = None,
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
        try:
            return tools.pr_url(str(value))
        except ValueError as e:
            self.fail(str(e), param, ctx)


class CursorType(click.ParamType[tuple[str, str], object]):
    """A `--cursor NAME=ID` pair; the id is later rendered into prompts, so it is kept short and plain."""

    name = "NAME=ID"

    @override
    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> tuple[str, str]:
        cursor_name, sep, cursor_id = str(value).partition("=")
        try:
            return tools.cursor(cursor_name if sep else "", cursor_id)
        except ValueError as e:
            self.fail(str(e), param, ctx)


class CheckoutType(click.ParamType[tuple[str, Path], object]):
    """A `--git NAME=PATH` checkout the read-only git tools may read: a repository's name and an absolute path."""

    name = "NAME=PATH"

    @override
    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> tuple[str, Path]:
        try:
            return git_tools.parse_checkout(str(value))
        except ValueError as e:
            self.fail(str(e), param, ctx)


class TextType(click.ParamType[str, object]):
    """Free text the overseer writes into the journal: stripped, non-empty, bounded."""

    name = "TEXT"

    @override
    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> str:
        try:
            return tools.clean_text(str(value))
        except ValueError as e:
            self.fail(str(e), param, ctx)


class TitleType(click.ParamType[str, object]):
    """A ticket's title: one line, control characters dropped, whitespace collapsed, non-empty, and cut."""

    name = "TITLE"

    @override
    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> str:
        try:
            return tools.clean_title(str(value))
        except ValueError as e:
            self.fail(str(e), param, ctx)


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
PERSONA = PatternType("NAME", config.PERSONA_NAME_RE, "persona name")
EVAL_CASE = PatternType("NAME", config.EVAL_CASE_RE, "eval case name")
