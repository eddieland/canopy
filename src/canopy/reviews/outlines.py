"""The outline of the PR's code a reviewer's prompt starts with (DESIGN §46, ROADMAP M70 stage 1).

At `index.outline = "tree"`, a review's start renders the tree of the commit it reviews as a directory tree
(`core.code_outline`), read from git's objects in the slot it leased, never from a checkout: nothing of the PR is
checked out or run for it (DESIGN §21). It is opened where the PR's diff against its base changed files. The tree is
read at the start, before `_review` fetches the commit, so a commit the slot does not hold yet, such as one only a
fork's PR holds, gets no outline, and the review goes on without it, as it does when git cannot list the tree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from canopy.core import code_outline
from canopy.infra import logs

if TYPE_CHECKING:
    from pathlib import Path

    from canopy.core import records
    from canopy.core.context import Context

#: The placeholder the reviewer's prompt carries its outline in.
OUTLINE = code_outline.OUTLINE
#: How much of the reviewed commit the outline names it by.
SHA_SHOWN = 12


def for_review(ctx: Context, run: records.ReviewRun, repo: str, slot: Path) -> str:
    """Return `{{OUTLINE}}`'s value for review run `run`, of the commit it reviews, in `repo`'s slot `slot`.

    Returns:
        The section, starting with the blank line that ends the one before it; empty with `index.outline` off, or when
        the slot does not hold the commit or git could not list its tree.
    """
    index = ctx.config.index
    if index.outline == "off":
        return ""
    log = logs.for_tick(run.tick_id)
    fields = {"review_run_id": run.id, "repo": repo, "sha": run.sha}
    if not code_outline.holds(ctx.runner, slot, run.sha):
        log.info("no code outline: the slot does not hold the reviewed commit", extra=fields)
        return ""
    try:
        listing = code_outline.listed(ctx.runner, slot, run.sha)
    except code_outline.Unlisted as e:
        log.warning("no code outline for a repository", extra={**fields, "error": str(e)})
        return ""
    tree = code_outline.render(listing, _about(ctx, run, slot), bound=index.outline_chars, exclude=index.exclude)
    return code_outline.section([code_outline.Tree(repo, run.sha[:SHA_SHOWN], tree)] if tree is not None else [])


def _about(ctx: Context, run: records.ReviewRun, slot: Path) -> code_outline.About:
    # The paths the PR changed since it left its base, as the lease last fetched the base; none, so the tree is opened
    # by size, when git cannot say.
    if not run.base_branch:
        return code_outline.About()
    base = f"refs/remotes/origin/{run.base_branch}"
    try:
        return code_outline.About(changed=code_outline.changed(ctx.runner, slot, base, run.sha))
    except code_outline.Unlisted as e:
        fields = {"review_run_id": run.id, "sha": run.sha, "error": str(e)}
        logs.for_tick(run.tick_id).warning("code outline opened by size: no diff", extra=fields)
        return code_outline.About()
