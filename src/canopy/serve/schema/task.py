"""The API's types for one-off tasks (DESIGN §36): the list, a task's page, a run, a report, and the operator's writes.

Built on `schema.Model`, as every API type is (schema/__init__.py). A task's text is the operator's; everything a run
wrote, its summary, question, and report among it, is an agent's: untrusted text, which the UI renders as text.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from canopy.serve.schema import Attachments, Message, Model, ModelsServed, RunState

type TaskStanding = Annotated[
    Literal[
        "queued",
        "running",
        "awaiting_reply",
        "blocked",
        "done",
        "failed",
        "unknown",
        "unpushed",
        "crashed",
        "timeout",
        "stopped",
    ],
    Field(
        description="Where a task stands (DESIGN §36): `queued` for a run a tick will start, its first or one a reply "
        "asked for; `awaiting_reply` while its latest run's question waits on the operator, which `canopy task list` "
        "words as the run's `blocked`; `stopped` once the operator stopped it and no run of it runs; else its latest "
        "run's status.",
    ),
]
type ReportProblem = Annotated[
    Literal["missing", "not a regular file", "unreadable", "not UTF-8", "empty", "over the bound"],
    Field(description="Why a kept report's file is not a report any more, as a plan's is read (DESIGN §25, §36)."),
]


class TaskRun(Model):
    """One run of a task's worker (DESIGN §36)."""

    id: int
    """The task run's id."""
    status: str
    """The journal's status: running, done, blocked, failed, unknown, unpushed, crashed, timeout, or stopped."""
    state: RunState
    """What the UI colors it as, as a ticket's run."""
    started_at: datetime
    """When it started."""
    ended_at: datetime | None = None
    """When it ended; None while it runs."""
    branch: str
    """The branch it worked on, `<branch_prefix>task/N`: every run of the task shares it."""
    head: str | None = None
    """The commit its branch was at on origin when it ended; None when nothing was pushed, or while it runs."""
    summary: str | None = None
    """The harness's note or the agent's summary, line breaks kept, cut at 300 characters: untrusted."""
    prs: list[str] = []
    """The PRs its result names, each a plain https:// URL."""
    reported: bool = False
    """Whether it left a report, kept in the state directory: its `report` route reads it."""
    session_id: str | None = None
    """The runtime's session, for opening its transcript with the runtime's own tools."""
    cost_usd: float | None = None
    """What the agent runtime reported it cost, in US dollars; None when it reported nothing."""
    new_tokens: int | None = None
    """The tokens the runtime reported its model took in or wrote anew, every kind but cache reads; None when it
    reported nothing."""
    peak_context: int | None = None
    """The most tokens one of its model calls was sent; None when the runtime reported nothing."""
    log_path: str
    """Where its log is: from the workspace root when under it."""
    served: list[str] = []
    """The models its session names as having served it, as `provider/model`, the most costly first; empty until
    canopy reads the session, and when none did. The runs page's `?model=` keeps the runs one served."""


class TaskSummary(Model):
    """A task as `canopy task list` lists it: its text, where it runs, and where it stands."""

    id: int
    """The task's id, as `task:N` names it."""
    text: str
    """The operator's words, control characters dropped and line breaks kept."""
    repo: str
    """The repository it runs in."""
    project: str | None = None
    """The tracker project its tickets may go in; None when it files none."""
    branch: str
    """The branch its runs work on, `<branch_prefix>task/N`."""
    channel: str
    """Where the operator submitted it: cli or web."""
    submitted_at: datetime
    """When the operator submitted it."""
    stopped_at: datetime | None = None
    """When the operator stopped it; None while it is not stopped."""
    standing: TaskStanding
    """Where it stands now."""
    question_id: int | None = None
    """The message of its latest run's that asks the operator a question no reply has followed, while not stopped."""
    latest: TaskRun | None = None
    """Its newest run; None before its first starts."""
    runs: int = 0
    """How many runs it has had."""


class TaskTicket(Model):
    """A ticket a task's run reported filing in the task's project, unlabeled, worked only once the operator says so."""

    key: str
    """The ticket's key, as the run's result spelled it."""
    run_id: int
    """The task run that reported it."""
    at: datetime
    """When canopy recorded it."""


class TaskDetail(Model):
    """One task: what `canopy show task:N` prints."""

    task: TaskSummary
    """The task, as the tasks list shows it."""
    runs: list[TaskRun]
    """Every run of it, the oldest first."""
    messages: list[Message]
    """Its conversation, the oldest first: its runs' reports and questions, and the operator's replies."""
    tickets: list[TaskTicket]
    """The tickets its runs filed, the oldest first."""
    attachments: Attachments
    """The files the operator attached to it, which its runs read (DESIGN §22)."""


class TaskRunDetail(Model):
    """One task run: its row as its task's page lists it, and the whole of what it reported (DESIGN §36)."""

    task_id: int
    """The task it is a run of."""
    run: TaskRun
    """The run, as its task's page lists it."""
    summary: str | None = None
    """The agent's summary, line breaks kept and not cut: untrusted."""
    question: str | None = None
    """The question a `blocked` run asked the operator, line breaks kept: untrusted."""
    note: str | None = None
    """Why the harness decided the run's status, when it did: a timeout, a crash, a result that did not validate."""
    tickets: list[TaskTicket] = []
    """The tickets canopy recorded from its result."""
    models: ModelsServed
    """Which models served it."""


class TaskReport(Model):
    """The report a task run left, as its file in the state directory stands now (DESIGN §36), as a plan is read."""

    task_id: int
    """The task it is a report of."""
    run_id: int
    """The run that left it."""
    path: str
    """Its file, `<state_dir>/tasks/<task>/<run>.md`: from the workspace root when under it, as a log path is."""
    text: str | None = None
    """Its Markdown, control characters dropped, or none when the file is not a report any more: `problem` says why.
    Agent-written and untrusted: the UI renders it as text."""
    problem: ReportProblem | None = None
    """Why it is not: missing, not a regular file, unreadable, not UTF-8, empty, or over the bound."""
    sha256: str | None = None
    """The file's hash now, whenever it could be read."""
    edited: bool = False
    """Whether the file has changed since its run left it."""


class TaskSubmitRequest(Model):
    """A task's text, in the operator's words, and where it runs, as `canopy task submit` takes them."""

    text: Annotated[str, Field(max_length=20_000)]
    """The task's text. Bounded again in code at 4000 characters, after stripping (DESIGN §36)."""
    repo: Annotated[str, Field(max_length=200)] | None = None
    """The repository it runs in, as `--repo` names it. Required when the workspace has several."""
    project: Annotated[str, Field(max_length=200)] | None = None
    """The tracker project its tickets may go in, as `--project` names it. None: it files no tickets."""


class TaskSubmitted(Model):
    """What a submission recorded: the task, queued for the next tick, and where it will run."""

    id: int
    """The task's id, as `task:N` names it."""
    repo: str
    """The repository it runs in."""
    branch: str
    """The branch every run of it works on, `<branch_prefix>task/N`."""
    no_capacity: bool
    """Whether `capacity.max_tasks` is 0, so no tick starts it until the operator raises it."""


class TaskReplied(Model):
    """What a reply recorded, as `canopy reply task:N` says: the message, what it answers, and what starts next."""

    message_id: int
    """The message the reply is."""
    answers: int | None = None
    """The question it answers, if it answers one."""
    new: bool
    """Whether it was recorded now, rather than by an earlier submission with the same id."""
    running_run: int | None = None
    """A run of the task still working: the first tick after it ends starts the next. None: the next tick does."""


class TaskStopped(Model):
    """What a stop did, as `canopy stop task:N` says: no tick starts the task again."""

    already: bool
    """Whether the task was already stopped."""
    dropped: bool
    """Whether it was still queued, its first run or one a reply asked for, which nothing starts now."""
    running_run: int | None = None
    """A run of it still working, if one is: it finishes unless `now` ended it."""
    ended: bool = False
    """Whether `now` ended that run and returned its slot."""
