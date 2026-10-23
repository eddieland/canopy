"""The API's types for canopy's reviews (DESIGN §21) and the PRs the journal knows (DESIGN §22).

Review runs, their findings on their diffs, the operator's review requests, and what the operator does with a
review: dismiss a finding, mark it seen, send findings to a worker. Built on `schema.Model`, as every API type is
(schema/__init__.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import CostTotal, Decision, Limit, Model, ModelsServed, Run, RunState

type ReviewVerdict = Annotated[Literal["clean", "findings"], Field(description="A review run's verdict (DESIGN §21).")]
type ReviewImpact = Annotated[
    Literal["low", "normal", "high"],
    Field(description="A change's impact, as the reviewer calls it: `low` as `review.low_impact` allows (DESIGN §21)."),
]
type FindingSeverity = Annotated[
    Literal["blocking", "major", "minor"],
    Field(description="How much a review finding matters (DESIGN §21)."),
]
type ReviewDraftStatusName = Annotated[
    Literal["waiting", "publishing", "unconfirmed", "staged", "published", "discarded"],
    Field(
        description="Where a review's draft stands (DESIGN §34): the operator's to edit and publish while `waiting`; "
        "`staged` in a pending review for them to submit on GitHub; `unconfirmed` until a read says whether it posted; "
        "`discarded` once they said it will not post.",
    ),
]
type DiffLineKind = Annotated[
    Literal["add", "del", "ctx"],
    Field(description="Whether a diff line is added, deleted, or context."),
]


class ReviewSummary(Model):
    """One review run of a PR at a commit (DESIGN §21): canopy's own review, which is never on the PR (D114)."""

    id: int
    """The review run's id."""
    pr_url: str
    """The PR's URL as the overseer gave it: an opaque https:// string."""
    sha: str
    """The commit it reviewed."""
    ticket_key: str | None = None
    """The ticket the PR is for, when it is for one."""
    title: str | None = None
    """The PR's title as the PR pages give it: its own, else its ticket's; None when neither is known."""
    repo: str | None = None
    """The PR's repository, as the workspace names it."""
    status: str
    """The journal's status: running, done, failed, unknown, timeout, crashed."""
    state: RunState
    """`done` is done; every other ending is failed."""
    verdict: ReviewVerdict | None = None
    """Its verdict, once it reported one."""
    impact: ReviewImpact | None = None
    """The change's impact, once it reported one."""
    findings: int = 0
    """How many findings it reported."""
    worst: FindingSeverity | None = None
    """The severity of the worst finding it reported, which colors its verdict; None when it reported none."""
    worst_count: int = 0
    """How many of its findings are of the worst severity, which its verdict says in words (`3 findings, 1 major`)."""
    started_at: datetime
    """When it started."""
    ended_at: datetime | None = None
    """When it ended; None while it runs."""
    cost_usd: float | None = None
    """What the agent runtime reported it cost, in US dollars; None when it reported nothing."""
    persona: str | None = None
    """The persona it ran in (DESIGN §31); None for a review from before canopy recorded it."""
    request_id: int | None = None
    """The operator's review request it answers (DESIGN §21), which its reviews in the request's other personas share
    (§31); None for a review the loop started on its own."""
    news: bool = False
    """Whether it has a result for the operator to read: it ended with a verdict that found something, or with any
    verdict when they asked for it. A clean review the loop started on its own has none."""
    seen: bool = False
    """Whether the operator has seen it, on its page or with `canopy review show ID` (DESIGN §22). A run with news
    that is not seen is new to them."""
    draft: ReviewDraftStatusName | None = None
    """Where its draft stands (DESIGN §34); None for a review that has none, such as one of the loop's own PRs."""


class RequestedReview(Model):
    """A PR the operator asked canopy to review that no review of is running yet: it waits on a tick (DESIGN §21)."""

    pr_url: str
    """The PR's URL, as the operator gave it: an opaque https:// string."""
    created_at: datetime
    """When the operator asked."""
    channel: str
    """Where they asked: `cli` or `web`."""
    author: str | None = None
    """The PR's author, as canopy's reader last read the PR; None until it has."""


class ReviewFinding(Model):
    """One finding, with where it falls in the diff: `file` indexes the diff's files, `line` is on the new side.

    Both are None when the diff does not show the file; `line` alone is None when it does not show the line.
    """

    severity: FindingSeverity
    """How much it matters."""
    title: str
    """Its title, as the reviewer wrote it: untrusted text."""
    location: str
    """Where it is, as the reviewer wrote it: `path:line`, say. Untrusted text."""
    detail: str
    """Its detail, as the reviewer wrote it: untrusted text."""
    file: int | None = None
    """The index in the diff's files of the file it is in; None when the diff does not show it."""
    line: int | None = None
    """The line it is on, on the new side; None when the diff does not show it."""
    dismissed: bool = False
    """Whether the operator dismissed it: no worker or tick acts on it (DESIGN §21)."""


class DiffLine(Model):
    """One line of a hunk, with its number on each side it is on."""

    kind: DiffLineKind
    """Whether it is added, deleted, or context."""
    old: int | None = None
    """Its number on the old side; None for an added line."""
    new: int | None = None
    """Its number on the new side; None for a deleted line."""
    text: str
    """The line's text, without its `+`, `-`, or space: untrusted."""


class DiffHunk(Model):
    """One hunk: what follows its `@@` ranges, such as a function's name, and its lines."""

    header: str
    """What follows the hunk's `@@` ranges, such as a function's name."""
    lines: list[DiffLine]
    """Its lines."""


class DiffFile(Model):
    """One file the commit changes. `old_path` when it was renamed; `binary` when git shows no lines for it."""

    path: str
    """The file's path in the repository."""
    old_path: str | None = None
    """Its path before, when it was renamed."""
    binary: bool = False
    """Whether git shows no lines for it."""
    hunks: list[DiffHunk]
    """Its hunks."""


class ReviewDiff(Model):
    """The reviewed commit's diff against where it leaves its base branch: the PR's own text, untrusted, and bounded."""

    files: list[DiffFile]
    """The files it changes."""
    truncated: bool = False
    """A bound left something out."""


type ReviewDraftAuthorName = Annotated[
    Literal["reviewer", "reviser", "operator"],
    Field(description="Who wrote a version of a review's draft: the review, a revision, or the operator."),
]


class ReviewDraftComment(Model):
    """One comment of a review's draft, on a line of the diff the review kept: the reviewer's text until published."""

    number: int
    """Its number in the version, from 1: how an edit or a drop names it."""
    path: str
    """The file it is on."""
    line: int
    """The line it is on, in the commit's file, on the diff's new side."""
    text: str
    """Its text, as the version holds it: plain text here, untrusted until the operator publishes it."""
    finding: int | None = None
    """The review's finding it was made from, by number; None for one the operator added."""
    file: int | None = None
    """The index of its file in the diff; None once the diff is gone."""
    diff_line: int | None = None
    """Its line on the diff's new side; None once the diff is gone."""


class ReviewDraftVersion(Model):
    """One version of a review's draft, as its history lists it."""

    number: int
    """The version's number, from 1."""
    hash: str
    """The name a publish carries: its body's and its comments' hash."""
    author: ReviewDraftAuthorName
    """Who wrote it."""
    channel: str | None = None
    """For the operator's, where they wrote it: `cli` or `web`."""
    change: str
    """What made it, in the harness's words."""
    created_at: datetime
    """When it was made."""


class ReviewDraftNote(Model):
    """The operator's note on a review's draft, as `canopy reply review:ID` records it: what to revise in it."""

    id: int
    """The note's id."""
    body: str
    """The note, in the operator's words: the reviser's only instructions."""
    channel: str
    """Where they wrote it: `cli` or `web`."""
    after_version: int
    """The draft's newest version when they wrote it: the note asks for a revision while that is still the newest."""
    created_at: datetime
    """When they wrote it."""


class ReviewDraftRevision(Model):
    """One revision of a review's draft (DESIGN §34): a review run on the operator's notes, its result a new version.

    It runs at the commit the review read, and reads the PR and the draft's newest version.
    """

    id: int
    """The revision's review run id."""
    status: str
    """The journal's status: running, done, failed, unknown, timeout, crashed."""
    state: RunState
    """`done` is done; every other ending is failed."""
    revised: int
    """The version it read and revises."""
    started_at: datetime
    """When it started."""
    ended_at: datetime | None = None
    """When it ended; None while it runs."""


class ReviewDraft(Model):
    """A review of a PR the loop does not own as the comment review it would post (DESIGN §34), at its newest version.

    What it holds is exactly what would post: the body as the review's, each comment on its line. Its text is the
    reviewer's, written from the PR's, until the operator publishes it.
    """

    status: ReviewDraftStatusName
    """Where it stands."""
    why: str | None = None
    """The harness's words for its latest change of status, such as why a publish posted nothing."""
    version: int
    """Its newest version's number."""
    hash: str
    """That version's hash, which a publish carries, so what posts is what the page showed."""
    author: ReviewDraftAuthorName
    """Who wrote that version."""
    channel: str | None = None
    """For the operator's version, where they wrote it."""
    change: str
    """What made that version, in the harness's words."""
    refused: list[str]
    """What canopy left out as it made that version, and why, in the harness's words."""
    body: str
    """The review's body: plain text here, empty for comments alone."""
    comments: list[ReviewDraftComment]
    """Its comments, in the order they post."""
    max_comments: int
    """How many comments a version may carry; an addition past it is refused."""
    in_body: list[int]
    """The review's findings, by number, whose text the body holds, where no line of the diff took them: each still a
    point of the review, though no comment carries it."""
    versions: list[ReviewDraftVersion]
    """Every version, oldest first."""
    pr_author: str | None = None
    """The PR's author's login as canopy last read the PR, whose PR the review would post on: untrusted text; None
    when canopy has not read the PR, or the account is gone."""
    moved_head: str | None = None
    """The PR's head when canopy last read it, when that is past the commit the review read: its comments would show
    as outdated there. None when canopy has not read the PR, or its head is that commit."""
    published_at: datetime | None = None
    """When it was published; None until it is."""
    published_url: str | None = None
    """The review's URL on GitHub, once published."""
    notes: list[ReviewDraftNote]
    """The operator's notes no version has answered, oldest first: while there are any and it waits, the next tick
    revises it, unless they change it first."""
    revisions: list[ReviewDraftRevision]
    """Its revisions so far, however they ended, newest first."""
    revision_limit: int
    """How many revisions it may have: `policy.max_revisions_per_draft` plus the operator's grants. A note at it is
    refused."""


class ReviewDraftBodyRequest(Model):
    """A new body for a review's draft, as `canopy review edit RUN --body --text TEXT` takes it."""

    text: Annotated[str, Field(max_length=8000)]
    """The body, empty to post the comments alone. Bounded again in code, as the reviewer's text is."""


class ReviewDraftCommentRequest(Model):
    """A comment's new text, as `canopy review edit RUN --comment N --text TEXT` takes it."""

    text: Annotated[str, Field(min_length=1, max_length=8000)]
    """The comment's text. Bounded again in code, as the reviewer's text is."""


class ReviewDraftAddRequest(Model):
    """A comment to add on a line of the diff the review kept, as `canopy review edit RUN --add PATH:LINE` takes it."""

    path: Annotated[str, Field(min_length=1, max_length=1000)]
    """The file, by its path in the diff."""
    line: Annotated[int, Field(ge=1)]
    """The line, on the diff's new side."""
    text: Annotated[str, Field(min_length=1, max_length=8000)]
    """The comment's text. Bounded again in code, as the reviewer's text is."""


class ReviewDraftNoteRequest(Model):
    """A note asking for a revision of a review's draft, as `canopy reply review:ID TEXT` takes it."""

    text: Annotated[str, Field(max_length=8000)]
    """What the revision should change. Bounded again in code at 4000 characters, after stripping, and refused empty."""


class ReviewDraftNoted(Model):
    """What a note recorded, as `canopy reply review:ID` reports it: the note, and the draft as it now stands."""

    note: int
    """The note's id."""
    after_version: int
    """The version it asks a revision of: the draft's newest when it was written."""
    draft: ReviewDraft
    """The draft, its notes this one among them."""


class ReviewDraftPublishRequest(Model):
    """A publish of a review's draft, as `canopy review publish RUN HASH [--submit]` takes it."""

    hash: Annotated[str, Field(min_length=12, max_length=12, pattern=r"^[0-9a-f]+$")]
    """The hash of the version the page showed: any other version is refused `stale`."""
    submit: bool = False
    """Submit it on GitHub now, as `--submit` does, rather than leave it pending for the operator to submit there."""


class ReviewDraftPublished(Model):
    """What a publish did, as `canopy review publish` reports it: the draft as it now stands."""

    draft: ReviewDraft
    """The draft: published, staged, unconfirmed, or waiting again."""
    published: int
    """The version it posted, or tried to."""
    failed: str | None = None
    """Why nothing was posted, in the harness's words; None when it posted, staged, or may have."""


class ReviewDetail(Model):
    """One review run in full: its summary, findings, the diff they sit on, and the PR's other review runs."""

    review: ReviewSummary
    """The review run, as the reviews list shows it."""
    ticket_title: str | None = None
    """Its ticket's title, on one line; None when it has no ticket or the ticket no title."""
    summary: str | None = None
    """The reviewer's summary, line breaks kept: untrusted text."""
    note: str | None = None
    """The harness's note, when it decided the status."""
    base_branch: str | None = None
    """The branch the PR merges into."""
    findings: list[ReviewFinding]
    """Its findings, each anchored on the diff where it can be."""
    diff: ReviewDiff | None = None
    """None when there is no diff: a review from before diffs were kept, one whose base could not be read, or one
    retention removed."""
    diff_removed_after_days: int | None = None
    """Retention removed the diff, this many days after the review ended (DESIGN §26); None when it did not."""
    sendable: bool = False
    """Whether its findings can be sent to a worker: a `done` review of one of the loop's own PRs (DESIGN §21)."""
    draft: ReviewDraft | None = None
    """Its draft of a review on the PR, for a review of a PR the loop does not own (DESIGN §34); None for one of the
    loop's own PRs, one that did not end `done`, or one from before drafts were kept."""
    runs: list[ReviewSummary]
    """Every review run of the same PR, newest first, this one included."""
    new_tokens: int | None = None
    """The tokens the runtime reported its model took in or wrote anew, every kind but cache reads; None when it
    reported nothing."""
    peak_context: int | None = None
    """The most tokens one of its model calls was sent, from the cache or not; None when the runtime reported nothing,
    or recorded it before canopy kept it."""
    log_path: str
    """Where its log is: from the workspace root when under it."""
    persona: str | None = None
    """The persona it ran in (DESIGN §31); None for a review from before canopy recorded it."""
    persona_digest: str | None = None
    """The sha256 of the persona's text as its prompt carried it, in hex."""
    models: ModelsServed
    """Which models served it."""


class ReviewRequest(Model):
    """The operator's request to review a PR the loop does not own (DESIGN §21): open, or how it ended."""

    created_at: datetime
    """When the operator made it."""
    channel: str
    """Where it was made: `cli` or `web`."""
    ended_at: datetime | None = None
    """When it ended; None while it is open."""
    end_reason: Literal["reviewed", "merged", "closed", "unknown_repo", "stopped"] | None = None
    """Why it ended: a `done` review of the PR; the PR merged or closed first, or is in none of the workspace's
    repositories (the overseer's reading); or the operator stopped it. None while it is open."""
    notes: str | None = None
    """The operator's notes for the reviewer, which its prompt carries; None when the request has none."""
    personas: list[str] = []
    """The personas it is reviewed in, one review each, in the order chosen; none for `[personas] reviewer`'s."""


class ReviewRequestBody(Model):
    """A review request's notes and personas, as `canopy start URL --review --notes TEXT --persona NAME` gives them."""

    notes: Annotated[str, Field(max_length=20_000)] = ""
    """What the reviewer should know or look at closely. Bounded again in code at 4000 characters, after stripping;
    blank is none, and leaves an open request's notes as they were."""
    personas: Annotated[list[Annotated[str, Field(max_length=40)]], Field(max_length=10)] = []
    """The personas to review it in, one review each, side by side, each one `GET /personas` lists; none is
    `[personas] reviewer`'s, and leaves an open request's personas as they were."""


class ReviewRequested(Model):
    """What a review request recorded: the open request, and whether it was already open or replaced another."""

    request: ReviewRequest
    """The PR's open request."""
    already: bool
    """Whether it was already open, so nothing new was recorded."""


class ReviewRequestStopped(Model):
    """What stopping a review request did: the request as it was, and a review of the PR still running."""

    request: ReviewRequest
    """The request it ended, as `stopped`."""
    running_review: int | None = None
    """A review run of the PR still running, which finishes; None when none is."""


class PullRequestDraft(Model):
    """The newest draft of a review of a PR the loop does not own (DESIGN §34): the operator's review of it."""

    review_id: int
    """The review run whose draft it is, whose page holds it."""
    status: ReviewDraftStatusName
    """Where it stands."""


class PullRequest(Model):
    """A PR the journal knows (DESIGN §22): one a ticket's unit records, or one canopy reviewed, whoever's it is."""

    url: str
    """The PR's URL: an opaque https:// string canopy never parses."""
    ticket_key: str | None = None
    """The ticket whose unit records it, or the one a review of it named; None for a PR no ticket owns."""
    loop_pr: bool = False
    """Whether a ticket's unit records it: one of the loop's own PRs, which a review request refuses (`loop_pr`)."""
    ticket_title: str | None = None
    """That ticket's title, as the overseer named it; None until it does."""
    title: str | None = None
    """Its own title, as the worker that opened or last updated it reported it: untrusted text; None until one does."""
    repo: str | None = None
    """The PR's repository, as the workspace names it."""
    branch: str | None = None
    """The unit's branch; None for a PR no unit records."""
    phase: str | None = None
    """The unit's phase as the overseer last derived it, for display; None for a PR no unit records."""
    active_at: datetime
    """The newest of its ticket's last change, its review runs' starts and ends, and its review requests'."""
    running_run: int | None = None
    """A run of its ticket working now, whose page it opens."""
    reviews: int = 0
    """How many review runs it has had, however they ended."""
    latest_review: ReviewSummary | None = None
    """Its newest review run, or None when canopy has not reviewed it."""
    review_request: ReviewRequest | None = None
    """The operator's latest review request on it, open or ended; None when they never made one."""
    draft: PullRequestDraft | None = None
    """The newest of its reviews' drafts; None when none has one, as no review of the loop's own PRs does."""


class PullRequestDetail(Model):
    """One PR: the runs that pushed to it, canopy's reviews of it, and the decisions that name it."""

    pull_request: PullRequest
    """The PR, as the PRs list shows it."""
    review_limit: Limit | None = None
    """Its review runs against its limit (DESIGN §21); None when canopy has never reviewed it."""
    runs: list[Run]
    """Its ticket's runs that reported this PR, and any of its ticket's runs working now, newest first; at most 20."""
    reviews: list[ReviewSummary]
    """Every review run of it, newest first; each opens its own page, with its findings on its diff."""
    decisions: list[Decision]
    """The latest 20 decisions naming it, across ticks, newest first."""
    cost: CostTotal
    """What every run it lists cost, not only the 20 shown, and every review run of it."""
    threads: bool = False
    """Whether canopy has read its review threads or holds a draft for it (DESIGN §29): what
    `GET /pull-request/threads` serves."""


class ReviewDismissRequest(Model):
    """A dismissal of one of a review run's findings, by its number, or with `undo` the taking back of one."""

    finding: Annotated[int, Field(ge=1, le=20)]
    """The finding's number in the review, from 1."""
    undo: bool = False
    """Take the dismissal back, as `--undo` does."""


class ReviewDismissed(Model):
    """What a dismissal of a review's finding left: the finding, and whether it is now dismissed."""

    run: int
    """The review run's id."""
    finding: int
    """The finding's number in the review, from 1."""
    dismissed: bool
    """Whether it is now dismissed: false after an `undo`."""


class SeenRequest(Model):
    """Subjects the operator has seen, by their references, `review:4` (DESIGN §22)."""

    refs: Annotated[list[Annotated[str, Field(min_length=1, max_length=100)]], Field(min_length=1, max_length=100)]
    """Each subject's reference: `review:ID`, a review run whose result they saw."""


class SeenMarked(Model):
    """What a mark of subjects seen recorded: every subject named, and the ones not seen before."""

    refs: list[str]
    """Each subject named, as its reference, once."""
    new: list[str]
    """The ones not seen before, which this mark recorded."""


class ReviewSendRequest(Model):
    """Some of a review run's findings to send to a worker, by number, with the submission id the form drew."""

    findings: Annotated[list[Annotated[int, Field(ge=1, le=20)]], Field(min_length=1, max_length=20)]
    """The findings' numbers in the review, from 1."""
    submission: Annotated[str, Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
    """The id the form drew when the findings were picked, sent again unchanged on a retry."""


class ReviewSent(Model):
    """What sending a review's findings recorded: the operator message on the review's ticket that names them."""

    run: int
    """The review run's id."""
    findings: list[int]
    """The findings sent, by number."""
    ticket_key: str
    """The ticket the message went to."""
    message_id: int
    """The message, the operator's go-ahead on the findings."""
    new: bool
    """Whether it was recorded now, rather than by an earlier submission with the same id."""
