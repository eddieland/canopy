"""The API's types for the Reviews report (DESIGN §11): who reviews canopy's PRs, how soon, and what answering cost.

Read from the PRs and feedback a `vcs` source observed, the feedback plans and the resumes after them, and canopy's own
review runs, dismissals, and drafts. Built on `schema.Model`, as every API type is (schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime

from canopy.serve.schema import Model


class ReviewsPullRequest(Model):
    """A PR in the window: its feedback in it, how soon its first review came, and what answering cost."""

    url: str
    """The PR."""
    ticket_key: str
    """The ticket that owns it: its unit's, else the ticket of the first run that named it."""
    phase: str | None = None
    """Its unit's phase (DESIGN §7); None for a PR no unit of the loop's has."""
    waiting_since: datetime | None = None
    """When it began waiting on a review, as GitHub says: the first review asked for once it was ready, or when it was
    ready; None where the reader kept neither, as for a PR read before canopy kept them, or a draft."""
    first_review_at: datetime | None = None
    """When the first review at or after `waiting_since` came, in the window or before it; None without a start, or
    with no review yet."""
    first_review_hours: float | None = None
    """From `waiting_since` to `first_review_at`, in hours; None without both."""
    reviews: int
    """Its reviews made in the window, from people other than its author and not bots."""
    changes_requested: int
    """Of those, the ones that asked for changes."""
    comments: int
    """Its comments made in the window, from people other than its author and not bots."""
    rounds: int
    """The feedback plans made in the window that read it."""
    cost_usd: float | None = None
    """What those plans' runs and the resumes that went ahead on them cost, in US dollars; None when none reported."""
    ready_at: datetime | None = None
    """When it last became ready for review, as GitHub says; None where the reader kept none."""
    merged_at: datetime | None = None
    """When it merged, as GitHub says; None while open, or where the reader kept none."""
    hours_to_merge: float | None = None
    """From `ready_at` to `merged_at`, in hours; None without both."""
    approved: int
    """Its reviews made in the window that approved it."""
    approved_at: datetime | None = None
    """When its first approval came, in the window or before it; None with none."""
    rounds_to_approval: int | None = None
    """The feedback plans that read it and were approved before its first approval, in the window or before it; a
    plan written before it and approved after does not count. None without an approval."""


class ReviewsReviewer(Model):
    """Someone who left feedback in the window on its PRs, by login."""

    author: str
    """Their login on the host."""
    trusted: bool
    """Whether `trust.trusted_reviewers` names them, so a worker may address their feedback unasked."""
    reviews: int
    """Their reviews made in the window."""
    changes_requested: int
    """Of those, the ones that asked for changes."""
    approved: int
    """Of those, the ones that approved."""
    comments: int
    """Their comments made in the window."""
    pull_requests: int
    """The PRs they reviewed."""
    median_wait_hours: float | None = None
    """The median, over the PRs they reviewed that have a start, of the wait from it to their first review at or after
    it, in hours; None with no such PR."""


class ReviewsDay(Model):
    """One local day of the window: the first reviews that arrived on it, by how long each waited."""

    day: str
    """The day, `YYYY-MM-DD`, in the local time of the machine canopy runs on."""
    start: datetime
    """When it starts: its local midnight, so a page can write it in its own zone."""
    first_reviews: list[int]
    """Its first reviews by wait: under an hour, one to four hours, four hours to a day, and a day or more."""
    median_wait_hours: float | None = None
    """Their median wait, in hours; None with none."""


class ReviewsTurnaround(Model):
    """How long canopy took to answer feedback, in four parts, from the feedback to the push that answered it."""

    to_plan_hours: float
    """From the feedback that started the round to its feedback plan, in hours."""
    to_approval_hours: float
    """From the plan to its approval, in hours."""
    to_resume_hours: float
    """From the approval to the start of the resume that went ahead on it, in hours."""
    to_push_hours: float
    """From the resume's start to the push that answered the feedback, in hours."""


class ReviewsRound(Model):
    """A feedback plan made in the window (DESIGN §32), with the resumes that went ahead on it."""

    plan_id: int
    """The plan."""
    ticket_key: str
    """Its ticket."""
    run_id: int
    """The feedback plan run that wrote it."""
    created_at: datetime
    """When it was written."""
    status: str
    """Where it stands: `proposed`, `approved`, or `superseded`."""
    approved_channel: str | None = None
    """How it was approved: by the operator through `web` or `cli`, or by the `planner` that judged it needs no
    review; None while not approved."""
    effort: str | None = None
    """How much work its planner judged it, `small`, `medium`, or `large`; None when it gave no estimate."""
    pull_requests: list[str]
    """The PRs it read."""
    plan_cost_usd: float | None = None
    """What its own run cost, in US dollars; None when it reported none."""
    resumes: int
    """The `resume` runs that went ahead on it."""
    resume_cost_usd: float | None = None
    """What they cost, in US dollars; None when none reported a cost."""
    review_at: datetime | None = None
    """When the feedback that started the round was made: the earliest, not an approval, on its PRs before the plan
    and after the last plan before it that went ahead; None when they had none."""
    approved_at: datetime | None = None
    """When it was approved; None while not."""
    resume_started_at: datetime | None = None
    """When the resume that went ahead on it started: the one that spent its approval, else the first; None without
    one."""
    resume_ended_at: datetime | None = None
    """When that resume ended; None without one, or while it runs."""
    answered_at: datetime | None = None
    """When a source first observed a check run on one of its PRs, after that resume started, on a head other than
    the one the plan read: the push that answered it. None while none, or for a PR whose checks no source observed."""
    turnaround_hours: float | None = None
    """From `review_at` to `answered_at`, in hours; None without both, or without an approval or a resume."""
    turnaround: ReviewsTurnaround | None = None
    """`turnaround_hours` in its parts, which sum to it; None where it is."""


class ReviewsEffort(Model):
    """The window's feedback plans of one effort as their planner judged it, beside the resumes that followed."""

    effort: str | None = None
    """`small`, `medium`, or `large`; None for the plans whose planner gave no estimate."""
    plans: int
    """The plans."""
    resumes: int
    """The `resume` runs that went ahead on them."""
    resume_cost_usd: float | None = None
    """What those resumes cost, in US dollars; None when none reported a cost."""


class ReviewsRunCount(Model):
    """canopy's review runs that started in the window, of one purpose and one status."""

    purpose: str
    """Why they ran: `own` for a PR of a ticket's, `request` for one the operator asked for, `query` for the rest."""
    status: str
    """How they ended, or `running`."""
    runs: int
    """How many."""
    cost_usd: float | None = None
    """What they cost, in US dollars; None when none reported a cost."""


class ReviewsDismissals(Model):
    """The findings of canopy's reviews the operator dismissed in the window, for one reason."""

    reason: str | None = None
    """`wrong`, `intentional`, `not_worth_it`, or `out_of_scope`; None for a dismissal from before canopy asked."""
    findings: int
    """How many."""


class ReviewsDrafts(Model):
    """The drafts of canopy's reviews made in the window that stand at one status (DESIGN §34)."""

    status: str
    """Where they stand: `published`, `discarded`, `waiting`, `staged`, `publishing`, or `unconfirmed`."""
    drafts: int
    """How many."""


class ReviewsReport(Model):
    """Where the window's review feedback came from, how long it took, and what answering it cost."""

    days: int
    """How many local days the window holds, today's so far included."""
    since: datetime
    """When the window starts: local midnight on its first day."""
    until: datetime
    """When it ends: local midnight after today."""
    reviews: int
    """The reviews made in the window on its PRs."""
    first_reviews: int
    """The first reviews that arrived in the window on a PR with a start, timed on GitHub's clock."""
    median_first_review_hours: float | None = None
    """Their median wait, in hours; None with none."""
    untimed: int
    """The window's PRs reviewed in it that have no start, read before canopy kept GitHub's times or a draft: counted
    apart, never in a median."""
    waiting: int
    """The window's open PRs that began waiting on a review and have none yet."""
    turnarounds: int
    """The window's feedback rounds that were answered, with the feedback that started them: those that have a
    `turnaround_hours`."""
    median_turnaround_hours: float | None = None
    """Their median `turnaround_hours`; None with none."""
    median_turnaround: ReviewsTurnaround | None = None
    """The median of each part over the same rounds, to say where the time went; None with none. Each part's median
    is its own, so they need not sum to `median_turnaround_hours`."""
    per_day: list[ReviewsDay]
    """Every day of the window, oldest first."""
    reviewers: list[ReviewsReviewer]
    """The most reviews first."""
    pull_requests: list[ReviewsPullRequest]
    """The window's PRs, the one a run named last first."""
    rounds: list[ReviewsRound]
    """The newest first."""
    efforts: list[ReviewsEffort]
    """`small` to `large`, then no estimate; only those with a plan."""
    review_runs: list[ReviewsRunCount]
    """By purpose, then by status."""
    dismissals: list[ReviewsDismissals]
    """The most first."""
    drafts: list[ReviewsDrafts]
    """The most first."""
    canopy_trusted: bool
    """Whether `trust.trusted_reviewers` names `canopy:review`, so a worker addresses canopy's own findings unasked."""
