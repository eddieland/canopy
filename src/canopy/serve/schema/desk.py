"""The API's types for the operator's desk (DESIGN §18): a ticket's branch checked out in a slot per repository.

What a ticket's page shows of its desk, and what opening or closing one did, as `canopy desk KEY` and its `--close` say
it. Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from canopy.serve.schema import Model


class DeskSlot(Model):
    """One repository's slot at the desk: where the ticket's branch is checked out for the operator."""

    repo: str
    """The repository, as the workspace names it, which is also the desk's link to the slot."""
    path: str
    """The slot's worktree, from the workspace root when it is under it, as the worktrees page shows a path."""


class OpenDesk(Model):
    """A ticket's desk while it is open: where it is, the branch, each slot, and how to open it in an editor."""

    branch: str
    """The ticket's branch, checked out in every slot as a local branch tracking origin's."""
    path: str
    """The desk's directory, `checkouts/KEY`, from the workspace root."""
    workspace_file: str
    """The editor's workspace file in it, whole, which opens every slot in one VS Code window."""
    open_command: str
    """The command that opens it in VS Code, as `canopy desk KEY` prints it, its path quoted for a shell."""
    editor_url: str
    """A `vscode:` link that opens the workspace file, through VS Code's WSL remote when canopy runs inside WSL."""
    slots: list[DeskSlot]
    """Each repository's slot, in the workspace map's order."""


class TicketDesk(Model):
    """What the ticket's page shows of its desk: the repositories one could cover, and the desk, while open."""

    repos: list[str]
    """The repositories with the ticket's branch, which a desk covers unless the operator names fewer; none before its
    first implement names a branch, when no desk can open."""
    open: OpenDesk | None = None
    """The desk, while it is open; None when it is closed."""


class DeskRequest(Model):
    """An open of a ticket's desk, as `canopy desk KEY [--repo NAME]...` asks for one."""

    repos: Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=100)] = []
    """The repositories it covers, each one with the ticket's branch; none means every one with it."""


class DeskOpened(Model):
    """What opening a ticket's desk did, or that it was already open, and the run working the ticket meanwhile."""

    already: bool
    """It was already open, and stays as it was: closing it is how its repositories change."""
    desk: OpenDesk
    """The desk, open."""
    running_run: int | None = None
    """The run working the ticket now, in slots of its own, which pushes to the same branch; None when none is."""
    running_kind: str | None = None
    """That run's kind."""


class DeskCloseRequest(Model):
    """A close of a ticket's desk, and whether it loses work origin lacks, as `canopy desk KEY --close` does."""

    discard: bool = False
    """Lose uncommitted changes and commits origin lacks, as `--discard` does; without it such a desk is refused."""
    confirm: Annotated[str | None, Field(max_length=200)] = None
    """With `discard`, the ticket's key, typed by the operator: what is lost cannot be had back, so anything else is
    refused `not_confirmed`."""


class DeskClosed(Model):
    """What closing a ticket's desk did: the repositories whose slots it returned, none when no desk was open."""

    returned: list[str]
    """Each repository whose slot went back to its pool; empty when the ticket had no desk open."""
