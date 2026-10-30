"""Validated click parameter types for what the operator passes in, and how a command builds a request.

Keys and names reach branch names, paths, argv, and prompts, so they are checked before any command runs, by the same
checks the overseer's tools make (`loop.tools`). Repository and chore names also complete in the shell, from the config
of the workspace the shell is in.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, override

import canopy_mcp
import click
from click.shell_completion import CompletionItem
from pydantic import ValidationError

from canopy.chores import install
from canopy.core import config, git_tools, workspace
from canopy.loop import tools
from canopy.loop.tools import KEY_RE

if TYPE_CHECKING:
    from pydantic import BaseModel


def validated[R: BaseModel](click_ctx: click.Context, request: type[R], **fields: object) -> R:
    """Build a request from a command's parameters, such as `canopy chore history`'s, which a tool shares.

    Returns:
        The request, validated.

    Raises:
        click.UsageError: It does not validate, saying why as its tool would.
    """
    try:
        return request.model_validate(fields)
    except ValidationError as e:
        raise click.UsageError(canopy_mcp.explain(e), click_ctx) from None


class PatternType(click.ParamType[str, object]):
    """A string that must match a pattern: ticket keys, and names of repositories, chores, and personas."""

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
    """Free text a command writes into the journal or a prompt, such as `chore try --context`: stripped, bounded."""

    name = "TEXT"

    @override
    def convert(self, value: object, param: click.Parameter | None, ctx: click.Context | None) -> str:
        try:
            return tools.clean_text(str(value))
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
REPO = PatternType("NAME", config.REPO_NAME_RE, "repository name", repo_names)
CHORE = PatternType("NAME", config.CHORE_NAME_RE, "chore name", chore_names)
# One of the example chores canopy ships, which `canopy chore install` sets up.
EXAMPLE_CHORE = PatternType("NAME", config.CHORE_NAME_RE, "chore name", install.available)
PERSONA = PatternType("NAME", config.PERSONA_NAME_RE, "persona name")
EVAL_CASE = PatternType("NAME", config.EVAL_CASE_RE, "eval case name")
