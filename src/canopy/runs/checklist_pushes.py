"""What a run pushed after canopy showed it a repository's checklist, read and kept as the run ends (DESIGN §42).

canopy's `pre-push` notes, in the slot's own git directory, the commit the branch was at each time it showed the run
its list, and each push it let through after a hold (`commit_hooks.pushes_after`). Once the worker has ended and its
work is on origin, `keep` reads those notes for one slot and keeps the diff of each stretch beside the run's log, from
the commit it was shown at to the commit of the next push, or to the one the run left on origin when no push followed:
what the run changed after being shown the list, with whatever else it did in that stretch. The commit it was shown
at may be one the run never pushed, whose objects go with the run's, so the diff is kept now or never.

The notes are the run's to write: each commit is checked to be one, and a stretch git cannot diff is dropped. Best
effort throughout, as a kept diff is (§29): the run needs none of it, so a failure is logged, and loses only the record.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from canopy.core import checklist_answers, commit_hooks, review_diff
from canopy.runs import checkpoint

if TYPE_CHECKING:
    from canopy.infra import logs


def keep(
    git: checkpoint.Git,
    *,
    repo: str,
    branch: str,
    run_id: str,
    log_path: str | Path,
    log: logs.TickAdapter,
) -> list[checklist_answers.Pushed]:
    """Keep the diff of each push run `run_id` made to `repo` after being shown its list, in the slot `git` runs in.

    `run_id` is the run's `CANOPY_RUN_ID`, as the hook noted it. `branch` is the run's, whose commit on origin closes a
    stretch no push closed.

    Returns:
        Each stretch whose diff was kept, oldest first: the commit the list was shown at, and the commit after.
    """
    fields = {"repo": repo, "branch": branch}
    try:
        own = git.run("rev-parse", "--absolute-git-dir")
        stretches = commit_hooks.pushes_after(Path(own), run_id)
        left = checkpoint.remote_head(git, branch) if any(sent is None for _, sent in stretches) else ""
    except checkpoint.SetupError as e:
        log.warning("checklist pushes not read", extra={**fields, "error": str(e)})
        return []
    kept: list[checklist_answers.Pushed] = []
    for shown, sent in stretches:
        pushed = sent or left
        if not pushed:
            continue
        try:
            # Commits alone, as the notes are the run's to write: a tree or a tag in one's place is no push.
            diff = git.result(*review_diff.diff_args(f"{shown}^{{commit}}", f"{pushed}^{{commit}}"))
            if not diff.ok:
                log.warning("checklist push not kept", extra={**fields, "shown": shown, "error": diff.stderr[:500]})
                continue
            review_diff.keep(checklist_answers.diff_path(log_path, repo, shown), diff.stdout)
        except (checkpoint.SetupError, OSError) as e:
            log.warning("checklist push not kept", extra={**fields, "shown": shown, "error": str(e)})
            continue
        kept.append(checklist_answers.Pushed(repo, shown, pushed))
    return kept
