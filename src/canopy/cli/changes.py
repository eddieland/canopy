"""`canopy show run:ID --diff` and `task:N --diff`: the run's own change, as it kept it, for a pager (DESIGN §45).

What a run changed in each repository is a diff the harness kept beside its log as the run ended (`runs.changes`). It
is the branch's text, untrusted, so it is read within `review_diff`'s bounds and printed with every control character
dropped, as a page shows it. What is not a diff, a repository's heading and why one was not kept, goes to stderr or a
`#` line, which a patch reader passes over.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

from canopy.cli.common import CliError
from canopy.core import review_diff, run_changes
from canopy.infra.text import one_line

if TYPE_CHECKING:
    from collections.abc import Sequence

    from canopy.core import records

#: How many characters of a commit a heading names.
_SHORT = 12


def echo(changes: Sequence[records.RunChange], *, log_path: str, ref: str) -> None:
    """Print the kept diff of the run's own change in each repository; a joint run's and an unpushed one's headed.

    Raises:
        CliError: the run kept no diff of its change in any repository, with why.
    """
    if not changes:
        raise CliError(f"canopy recorded nothing of what {ref} changed: it ran no worker, or was closed without it")
    printed = 0
    for c in changes:
        found = review_diff.text(run_changes.change_path(log_path, c.repo)) if c.change_kept else None
        if found is None:
            why = one_line(c.missing or "") if not c.change_kept else "its file is gone, removed with the run's others"
            click.echo(f"canopy: {ref} kept no diff of its change to {c.repo}: {why}", err=True)
            continue
        if len(changes) > 1 or c.unpushed_sha is not None:
            click.echo(f"# {c.repo}: {_span(c)}")
        for line in found.lines:
            click.echo(line)
        if found.truncated:
            click.echo(f"canopy: {ref}'s diff of {c.repo} is cut where canopy's bounds end", err=True)
        printed += 1
    if not printed:
        raise CliError(f"{ref} kept no diff of what it changed")


def _span(change: records.RunChange) -> str:
    """Return a heading's range: from the commit the run started from to the one its diff is of."""
    start = (change.start_sha or "")[:_SHORT]
    if change.unpushed_sha is not None:
        return f"{start}..{change.unpushed_sha[:_SHORT]}, not on origin: the run left it unpushed"
    return f"{start}..{(change.end_sha or '')[:_SHORT]}"
