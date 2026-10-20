"""The journal's closed vocabularies: run, tick, start, plan, and draft statuses, run kinds and reasons, and more.

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
    """A worker run's status, `runs.status` (DESIGN §8)."""

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


class TickStatus(StrEnum):
    """A tick's status, `ticks.status` (DESIGN §6)."""

    RUNNING = "running"
    OK = "ok"
    # The overseer skipped the whole tick: it could not see the world (`mcp_unavailable`, `tracker_unsupported`).
    SKIPPED = "skipped"
    # `canopy --version` failed from the overseer's environment, so the overseer did not run.
    CANOPY_UNAVAILABLE = "canopy_unavailable"
    # The state directory's or the workspace's filesystem had less than `loop.min_free_disk_mib` free, so the overseer
    # did not run.
    DISK_LOW = "disk_low"
    OVERSEER_FAILED = "overseer_failed"
    RECONCILE_FAILED = "reconcile_failed"
    # The tick raised an unexpected exception; its summary names it.
    ERROR = "error"
    # The tick's process exited without closing it; the next tick closed it.
    ABANDONED = "abandoned"


class RunKind(StrEnum):
    """What a worker run does, `runs.kind` (DESIGN §8)."""

    IMPLEMENT = "implement"
    # Retired (M56): a `resume` with the reason `ci` fixes CI. Kept so the runs it named still read, and count as
    # `resume` runs (DESIGN §8); nothing dispatches it.
    FIX_CI = "fix-ci"
    RESUME = "resume"
    # Retired (M46): workers file follow-up tickets instead (DESIGN §18). Kept so the runs it named still read, counted
    # per ticket and in no unit's attempts; nothing dispatches it.
    SPLIT = "split"
    # Writes a plan before a ticket's first implement (DESIGN §25): no branch, attempts counted per ticket.
    PLAN = "plan"
    # Retired (M55): a triage that judged, before a ticket's first plan, whether its work needed one. Every ticket the
    # policy plans is planned now (DESIGN §25). Kept so the runs it named still read, counted per ticket and in no
    # unit's attempts; nothing dispatches it.
    NEEDS_PLAN = "needs-plan"
    #: Writes a plan for what came back to a unit's PR, before the `resume` that acts on it (DESIGN §32): it reads the
    #: PR's head, pushes nothing, and counts per unit.
    FEEDBACK_PLAN = "feedback-plan"


class ResumeReason(StrEnum):
    """Why a `resume` runs, `run_reasons.reason` (DESIGN §8): each the phase, or the step, that sends it."""

    # `ci_red`: failed checks.
    CI = "ci"
    # `changes_requested` and `review_findings`: review feedback, or a canopy review's findings.
    REVIEW = "review"
    # `human_replied`: an authorized reply or an operator message.
    REPLY = "reply"
    # `conflicted`: the PR conflicts with its base.
    CONFLICT = "conflict"
    # `pushed_no_pr`: the branch is pushed and has no PR.
    NO_PR = "no_pr"
    # The PR's blocker merged, so it targets the repository's base branch again (DESIGN §10).
    RETARGET = "retarget"


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
    # Retired (M46), with split runs: kept so a ticket that still holds it reads; nothing sets it.
    SPLIT = "split"
    # The newest plan waits on the operator (DESIGN §25): no run, and the slot is free while they read it.
    PLAN_PROPOSED = "plan_proposed"


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


class PlanStatus(StrEnum):
    """A plan's status, `plans.status` (DESIGN §25): waiting on the operator, approved, or replaced."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    # A newer plan, a request for one, a skip, or `canopy forget` replaced it.
    SUPERSEDED = "superseded"


class Proposal(StrEnum):
    """What a feedback plan proposes for one of its items, `feedback_plan_items.proposal` (DESIGN §32)."""

    #: Change the code as the plan says, and reply saying so.
    CHANGE = "change"
    #: Change nothing for it, and reply saying why.
    DECLINE = "decline"
    #: A question the item raises before anything is changed for it.
    ASK = "ask"
    #: Nothing to do: no change and no reply.
    LEAVE = "leave"


class PlanSetting(StrEnum):
    """A ticket's own plan setting, `tickets.plan_setting` (DESIGN §25): it overrides `policy.plan`; NULL is unset."""

    PLAN = "plan"
    SKIP = "skip"


class StartStatus(StrEnum):
    """Whether the operator's start of a subject stands, `starts.status` (DESIGN §22).

    A stop never deletes the record, so a stopped ticket stays private.
    """

    STARTED = "started"
    STOPPED = "stopped"


class PoolKind(StrEnum):
    """Which pool made a worktree lease, `run_slots.pool` and `review_runs.pool`, and `pools.backend` (DESIGN §18)."""

    TREEHOUSE = "treehouse"
    CANOPY = "canopy"


class MemoryMode(StrEnum):
    """A memory tier's mode, `memory.ticket_notes` and `memory.proposals`, and `run_memory`'s columns (DESIGN §28)."""

    OFF = "off"
    # Workers write, and no agent reads what they wrote.
    RECORD = "record"
    USE = "use"


class MemoryScope(StrEnum):
    """What a memory is, `memories.scope` (DESIGN §28): a ticket's note, a worker's proposal, or a lesson."""

    TICKET = "ticket"
    PROPOSAL = "proposal"
    LESSON = "lesson"


class MemoryStatus(StrEnum):
    """Where a memory stands, `memories.status` (DESIGN §28)."""

    # A note or a lesson in force.
    ACTIVE = "active"
    # A proposal waiting on the operator.
    PENDING = "pending"
    # A newer one replaced it under its key, or a proposal the operator promoted.
    SUPERSEDED = "superseded"
    INVALID = "invalid"


class MemoryCited(StrEnum):
    """What a run said of a memory rendered into its prompt, `memory_reads.cited` (DESIGN §28)."""

    # In its `memory_used`: it relied on it.
    USED = "used"
    # In its `memory_wrong`: it found it wrong.
    WRONG = "wrong"


class MemoryAuthor(StrEnum):
    """Who wrote a memory, `memories.author` (DESIGN §28): a worker a note or a proposal, the operator a lesson."""

    WORKER = "worker"
    OPERATOR = "operator"


class ReplyMode(StrEnum):
    """`trust.review_replies`, and what a run was rendered under, `run_replies.mode` (DESIGN §29)."""

    # Workers draft every comment they would post; the operator sends them.
    APPROVE = "approve"
    # Workers post their own comments, marked.
    POST = "post"


class DraftKind(StrEnum):
    """Where a draft goes, `drafts.kind` (DESIGN §29)."""

    # A reply on a PR's review thread.
    THREAD = "thread"
    # A PR's one top-level comment: the body of the review its drafts are sent as.
    PR = "pr"
    # A comment on the ticket's issue.
    TICKET = "ticket"


class DraftStance(StrEnum):
    """What a thread's draft says the run did about it, `drafts.stance` (DESIGN §29)."""

    CHANGED = "changed"
    DECLINED = "declined"
    ANSWERED = "answered"


class DraftStatus(StrEnum):
    """Where a draft stands, `drafts.status` (DESIGN §29)."""

    # Waiting on a whole read of its PR before it can be sent.
    UNCHECKED = "unchecked"
    # Checked, and the operator's to send, edit, or drop.
    WAITING = "waiting"
    # The read did not return the thread it names, or its PR is not the run's.
    REFUSED = "refused"
    # A later run's draft for the same thread, PR, or ticket replaced it.
    SUPERSEDED = "superseded"
    DROPPED = "dropped"
    # Claimed by a send that is posting it now.
    SENDING = "sending"
    # A send ended without saying whether it posted; a read, or the operator, settles it.
    UNCONFIRMED = "unconfirmed"
    # In a pending review the operator opened through canopy, theirs to submit on GitHub; a read settles it.
    STAGED = "staged"
    SENT = "sent"


class DraftAuthor(StrEnum):
    """Who wrote a version of a draft's text, `draft_versions.author`: the run its first, the operator any later."""

    WORKER = "worker"
    OPERATOR = "operator"


class Reaction(StrEnum):
    """A reaction a thread's draft stages on the comment it names, `draft_versions.reaction` (DESIGN §29).

    Every one GitHub offers on a review comment, by the name its REST API and its web page give it.
    """

    THUMBS_UP = "+1"
    THUMBS_DOWN = "-1"
    LAUGH = "laugh"
    CONFUSED = "confused"
    HEART = "heart"
    HOORAY = "hooray"
    ROCKET = "rocket"
    EYES = "eyes"


class PrState(StrEnum):
    """A PR's state as canopy's reader last saw it, `observed_prs.state` (DESIGN §29)."""

    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


class ReviewItem(StrEnum):
    """What an observed review row is, `observed_reviews.item` (DESIGN §29)."""

    REVIEW = "review"
    COMMENT = "comment"


class ReviewState(StrEnum):
    """A review's state as GitHub reports it, `observed_reviews.state` (DESIGN §29)."""

    PENDING = "pending"
    COMMENTED = "commented"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    DISMISSED = "dismissed"


class SourceKind(StrEnum):
    """What a connector reads, `connector_runs.kind` and a `[connect.sources]` table's `kind` (DESIGN §30)."""

    TRACKER = "tracker"
    VCS = "vcs"


class ConnectorRunStatus(StrEnum):
    """How one run of a connector ended, `connector_runs.status` (DESIGN §30)."""

    #: It read everything it was asked.
    OK = "ok"
    #: It ended with its `end` line but read less than it was asked; what it read whole was recorded.
    PARTIAL = "partial"
    #: It did not start, timed out, printed too much, or ended without its `end` line; it recorded nothing.
    FAILED = "failed"


class TicketState(StrEnum):
    """A ticket's state as the tracker connector last saw it, `observed_tickets.state` (DESIGN §30)."""

    OPEN = "open"
    CLOSED = "closed"


class CheckStatus(StrEnum):
    """Where a CI context stands, `observed_checks.status` (DESIGN §30), in words a connector maps its host's onto."""

    REQUESTED = "requested"
    QUEUED = "queued"
    WAITING = "waiting"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class CheckConclusion(StrEnum):
    """How a completed CI context ended, `observed_checks.conclusion` (DESIGN §30)."""

    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"
    NEUTRAL = "neutral"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    ACTION_REQUIRED = "action_required"
    STARTUP_FAILURE = "startup_failure"
    STALE = "stale"


class MergeState(StrEnum):
    """Whether a PR can merge as its host says, `observed_prs.mergeable_state` (DESIGN §30)."""

    CLEAN = "clean"
    BEHIND = "behind"
    BLOCKED = "blocked"
    DIRTY = "dirty"
    DRAFT = "draft"
    HAS_HOOKS = "has_hooks"
    UNSTABLE = "unstable"
    UNKNOWN = "unknown"


class ModelsRead(StrEnum):
    """How canopy's last read of a run's session for its models ended, `run_model_reads.status` (DESIGN §13)."""

    #: The session was read: its models are in `run_models`.
    FOUND = "found"
    #: The runtime keeps no session of that id, which reading again would not change.
    MISSING = "missing"
    #: The runtime could not be asked, or said what canopy cannot read; read again later.
    FAILED = "failed"
