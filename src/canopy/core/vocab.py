"""The journal's closed vocabularies: a run's status and kind, a ticket's phase, and the pool a lease came from.

Each is a `StrEnum`, so a member is the string the journal stores and compares equal to it, and a misspelled one is a
type error rather than a silent wrong decision. Code that branches on one matches it with `typing.assert_never` in the
last case, so a value added here fails the type check until every branch handles it. A value read from the journal is
converted where it is branched on (`RunStatus(row["status"])`), which raises on one the vocabulary does not hold; a
table with a row type in `records` does that as the row is read, its column a field of the enum.

A table added from M36 on constrains each such column in SQL, `CHECK (status IN (...))` listing this module's values.
The tables `0001_init.sql` made keep their schema, since a shipped migration is never edited, and list their values in
comments.
"""

from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    """A worker or split run's status, `runs.status` (DESIGN §8)."""

    RUNNING = "running"
    DONE = "done"
    BLOCKED = "blocked"
    FAILED = "failed"
    # The worker's last line was not a valid result.
    UNKNOWN = "unknown"
    # The worker reported done with work it had not pushed.
    UNPUSHED = "unpushed"
    CRASHED = "crashed"
    TIMEOUT = "timeout"
    # The operator stopped it (DESIGN §22).
    STOPPED = "stopped"


class ChoreRunStatus(StrEnum):
    """A chore run's status, `chore_runs.status` (DESIGN §19)."""

    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    CRASHED = "crashed"


class ReviewRunStatus(StrEnum):
    """A review run's status, `review_runs.status` (DESIGN §21)."""

    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    CRASHED = "crashed"


# Any run table's status, for the lifecycle every run table shares (`db.finish_run`).
type AnyRunStatus = RunStatus | ChoreRunStatus | ReviewRunStatus


class RunKind(StrEnum):
    """What a worker run does, `runs.kind` (DESIGN §8)."""

    IMPLEMENT = "implement"
    FIX_CI = "fix-ci"
    RESUME = "resume"
    # Splits a ticket into children (DESIGN §18): it works on no branch, and counts attempts per ticket, not per unit.
    SPLIT = "split"


class Phase(StrEnum):
    """A ticket's or a unit's phase, in the order of the design's phase table (DESIGN §7)."""

    READY = "ready"
    BLOCKED = "blocked"
    RUNNING = "running"
    PUSHED_NO_PR = "pushed_no_pr"
    CONFLICTED = "conflicted"
    CI_RUNNING = "ci_running"
    CI_RED = "ci_red"
    REVIEW_PENDING = "review_pending"
    REVIEW_FINDINGS = "review_findings"
    CHANGES_REQUESTED = "changes_requested"
    UNTRUSTED_REVIEW = "untrusted_review"
    GREEN_UNREVIEWED = "green_unreviewed"
    APPROVED = "approved"
    MERGED = "merged"
    NEEDS_HUMAN = "needs_human"
    HUMAN_REPLIED = "human_replied"
    SPLIT = "split"


# The phases about a PR, `pushed_no_pr` to `merged` in the phase table, are a unit's (DESIGN §7, §18); the others are
# the ticket's own.
UNIT_PHASES = frozenset(
    {
        Phase.PUSHED_NO_PR,
        Phase.CONFLICTED,
        Phase.CI_RUNNING,
        Phase.CI_RED,
        Phase.REVIEW_PENDING,
        Phase.REVIEW_FINDINGS,
        Phase.CHANGES_REQUESTED,
        Phase.UNTRUSTED_REVIEW,
        Phase.GREEN_UNREVIEWED,
        Phase.APPROVED,
        Phase.MERGED,
    }
)


class PoolKind(StrEnum):
    """Which pool made a worktree lease, `run_slots.pool` and `review_runs.pool`, and `pools.backend` (DESIGN §18)."""

    TREEHOUSE = "treehouse"
    CANOPY = "canopy"
