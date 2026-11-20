"""The outline of its repositories' code a run's prompt starts with (DESIGN §46, ROADMAP M70 stage 1).

At `index.outline = "tree"`, a dispatch renders each repository a worker or a planner works in, and a task's start its
one, as a directory tree (`core.code_outline`), read from git's objects in the slot it leased. An `implement`'s and a
plan's tree is its base's, opened by the words of the ticket as the connector last observed it; a `resume`'s and a
feedback plan's is its branch's, opened where the branch already changed files; a task's is its base's, opened by the
task's own text. A tree git cannot list is left out and logged, and the run goes on without it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import code_outline, records
from canopy.core.vocab import RunKind
from canopy.infra import logs

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from canopy.core import db
    from canopy.core.context import Context

#: The placeholder a worker's, a planner's, and a task's prompt carries its outline in.
OUTLINE = code_outline.OUTLINE
#: The kinds whose prompt gets an outline: every kind a dispatch starts, the workers' and the planner's.
KINDS = (RunKind.IMPLEMENT, RunKind.RESUME, RunKind.PLAN, RunKind.FEEDBACK_PLAN)
#: The kinds whose tree is their branch's, opened where it changed: those that read a pushed branch's head.
_ON_BRANCH = (RunKind.RESUME, RunKind.FEEDBACK_PLAN)


def for_run(ctx: Context, tick_id: int, key: str, kind: str, *, branch: str, slots: Sequence[db.RunSlot]) -> str:
    """Return `{{OUTLINE}}`'s value for a run of `kind` on ticket `key` in `slots`.

    The bound, `index.outline_chars`, is shared evenly among the run's repositories.

    Returns:
        The section, starting with the blank line that ends the one before it; empty with `index.outline` off, for a
        kind that gets none, or when no repository's tree could be listed.
    """
    index = ctx.config.index
    if index.outline == "off" or kind not in KINDS or not slots:
        return ""
    words = _ticket_words(ctx, key)
    trees: list[code_outline.Tree] = []
    for slot in slots:
        base = f"refs/remotes/origin/{slot.base_branch}"
        ref, about = base, code_outline.About(words=words)
        try:
            head = f"refs/remotes/origin/{branch}"
            if kind in _ON_BRANCH and code_outline.holds(ctx.runner, slot.slot_path, head):
                ref = head
                changed = code_outline.changed(ctx.runner, slot.slot_path, base, head)
                # A branch that changed nothing yet is opened as its `implement` was.
                about = code_outline.About(words=words, changed=changed)
            listing = code_outline.listed(ctx.runner, slot.slot_path, ref)
        except code_outline.Unlisted as e:
            _unlisted(tick_id, {"ticket": key, "repo": slot.repo}, e)
            continue
        tree = code_outline.render(listing, about, bound=index.outline_chars // len(slots), exclude=index.exclude)
        if tree is not None:
            trees.append(code_outline.Tree(slot.repo, ref.removeprefix("refs/remotes/"), tree))
    return code_outline.section(trees)


def for_task(ctx: Context, tick_id: int, task: records.Task, *, slot: Path, base: str) -> str:
    """Return `{{OUTLINE}}`'s value for a run of `task` in `slot`, whose base branch is `base` (DESIGN §36).

    The tree is the base's as the lease last fetched it, opened by the words of the operator's text.

    Returns:
        The section, starting with the blank line that ends the one before it; empty with `index.outline` off, or when
        the tree could not be listed.
    """
    index = ctx.config.index
    if index.outline == "off":
        return ""
    ref = f"refs/remotes/origin/{base}"
    try:
        listing = code_outline.listed(ctx.runner, slot, ref)
    except code_outline.Unlisted as e:
        _unlisted(tick_id, {"task": task.id, "repo": task.repo}, e)
        return ""
    about = code_outline.About(words=code_outline.words(task.text))
    tree = code_outline.render(listing, about, bound=index.outline_chars, exclude=index.exclude)
    shown = [code_outline.Tree(task.repo, ref.removeprefix("refs/remotes/"), tree)] if tree is not None else []
    return code_outline.section(shown)


def _ticket_words(ctx: Context, key: str) -> frozenset[str]:
    # The words of ticket `key` as the connector last observed it; none for a ticket with no observation.
    seen = records.select(records.ObservedTicket).where("key = ?", key).one(ctx.conn)
    return code_outline.words(f"{seen.title}\n{seen.body}") if seen is not None else frozenset()


def _unlisted(tick_id: int, fields: Mapping[str, object], error: code_outline.Unlisted) -> None:
    # A tree git could not list costs the run its outline, never its start.
    logs.for_tick(tick_id).warning("no code outline for a repository", extra={**fields, "error": str(error)})
