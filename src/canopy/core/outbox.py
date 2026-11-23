"""The events notification sinks receive (DESIGN §20): a closed set, built here from what the harness already knows.

Dispatch, `_run`, `_chore`, and reconcile record them through `canopy.core.db` in the transaction that records the fact;
the `canopy.notify` feature delivers them. An event is recorded only when some sink takes its name
(`canopy.core.event_names`), so with no sinks no event is recorded. Text fields are cut to the limits DESIGN §20 lists
and kept to one line.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Final, TypedDict

from canopy.core import chore_result, contract, epic_outline, review_result
from canopy.core.db import Event
from canopy.core.vocab import RunStatus

if TYPE_CHECKING:
    from canopy.core import epic_changes, records, spend
    from canopy.core.config import Config
    from canopy.core.vocab import ChoreRunStatus, ReviewRunStatus

#: The attention list's diff: a group, and the name a sink takes it by, with no events of its own in the outbox.
ATTENTION: Final = "attention"
RUNS: Final = "runs"
LOOP: Final = "loop"
CHORES: Final = "chores"
REVIEWS: Final = "reviews"
#: A one-off task's runs (DESIGN §36): a group of its own, which no sink takes unless the operator lists it.
TASKS: Final = "tasks"
#: What canopy did with a reply it read from Slack (DESIGN §20): a mention it recorded, and any reply it refused.
REPLIES: Final = "replies"
#: The kind of the event that says the month's spend reached one of its budget's alerts.
BUDGET_REACHED: Final = "loop.budget_reached"
SUMMARY_LIMIT: Final = 300
DETAIL_LIMIT: Final = 500
#: How many follow-ups a `follow_ups.filed` event names; the rest are counted.
MAX_FOLLOW_UPS: Final = 20
#: How many ids an `epic.changed` event names; the rest are counted.
MAX_EPIC_IDS: Final = 40
#: What ends text `cut` shortened.
_ELLIPSIS: Final = "..."


class RunStarted(TypedDict):
    """A `run.started` event's fields."""

    ticket: str
    run: int
    run_kind: str
    branch: str
    attempt: int
    limit: int


class RunEnded(TypedDict):
    """A `run.ended` event's fields. `pr` is the first of `prs`; `question` is set only for a `blocked` run."""

    ticket: str
    run: int
    run_kind: str
    status: str
    branch: str | None
    pr: str | None
    prs: list[str]
    summary: str | None
    question: str | None
    message: int | None


class PlanProposed(TypedDict):
    """A `plan.proposed` event's fields: which plan waits on the operator, never its text (DESIGN §25)."""

    ticket: str
    run: int
    plan: int


class PlanApproved(TypedDict):
    """A `plan.approved` event's fields: a plan the harness approved on its planner's word that it needs no review.

    Never the plan's text (DESIGN §25).
    """

    ticket: str
    run: int
    plan: int
    #: Whether it is a feedback plan (DESIGN §32), not the ticket's plan.
    feedback: bool
    #: The planner's reason, model text cut to one line.
    reason: str


class EpicChanged(TypedDict):
    """An `epic.changed` event's fields: an approval of an epic's plan changed ids that reached its members (§43).

    Never the plan's text: its ids, and the members each way, which the operator decides on.
    """

    epic: int
    #: The epic plan approved.
    plan: int
    #: The ids it added, removed, or changed from the plan approved before it, in the plan's order, at most
    #: `MAX_EPIC_IDS`; `count` is how many.
    ids: list[str]
    count: int
    #: The members whose plan waited on the operator, superseded as stale.
    stale: list[str]
    #: The members whose approved plan's `implement` waits on the operator (`epic_changed`).
    held: list[str]
    #: The members left as they are, whose next run is told.
    told: list[str]


class FollowUpsFiled(TypedDict):
    """A `follow_ups.filed` event's fields: the follow-ups one run filed, each with its repository or null (§18).

    `follow_ups` names at most `MAX_FOLLOW_UPS`; `count` is how many the run filed.
    """

    ticket: str
    run: int
    follow_ups: dict[str, str | None]
    count: int


class CiFlaky(TypedDict):
    """A `ci.flaky` event's fields: a `resume` for `ci` left a failed check as not the change's (DESIGN §23)."""

    ticket: str
    run: int
    prs: list[str]
    #: The repositories whose branch canopy pushed again to rerun the check; empty when the operator reruns it.
    kicked: list[str]
    #: The worker's estimate of why the check is flaky, its `flaky_detail` or else its summary: model text, one line.
    estimate: str
    #: Where the worker judged the check failed, `test`, `runner`, or `service`, or None when it was not sure.
    cause: str | None
    #: A cause the worker named outside that vocabulary, as it said it, cut to one line; else None.
    other_cause: str | None
    #: Why a repository was not kicked, in the harness's words, or None.
    note: str | None


class CiKicked(TypedDict):
    """A `ci.kicked` event's fields: canopy force-pushed one PR's branch to rerun a check left as flaky (DESIGN §23).

    It is in the `loop` group, which sinks take by default, so the operator hears of every forced push canopy makes.
    """

    ticket: str
    run: int
    repo: str
    branch: str
    #: The PR the run's result named for `repo`, or None.
    pr: str | None
    #: The head the kick replaced, as origin had it.
    from_head: str
    #: The head the kick pushed, with a lease on `from_head`.
    to_head: str
    #: Which of the head's kicks this was, from 1, and `trust.max_flaky_kicks`.
    kick: int
    limit: int


class ChoreEnded(TypedDict):
    """A `chore.ended` event's fields: how a chore's run ended, its status alone."""

    chore: str
    run: int
    status: str
    #: Its summary on one line; None when it has none, or when a `chore.summary` event carries it whole.
    summary: str | None
    findings: int


class ChoreSummary(TypedDict):
    """A `chore.summary` event's fields: the summary of a chore whose table sets `whole_summary`, sent whole."""

    chore: str
    run: int
    #: The summary, a line of it each.
    lines: list[str]


class ReviewEnded(TypedDict):
    """A `review.ended` event's fields: how many findings, never what they are (D114)."""

    pr: str
    #: The repository the PR is in, as the workspace map names it; None when canopy cannot tell.
    repo: str | None
    ticket: str | None
    run: int
    status: str
    verdict: str | None
    impact: str | None
    findings: int


class TaskEnded(TypedDict):
    """A `task.ended` event's fields (DESIGN §36): how one run of a task ended, never its report.

    `question` is set only for a `blocked` run; `branch` and `head` only when the task's branch was on origin as the
    run ended; `pr` is the first of the PRs its result named.
    """

    task: int
    run: int
    status: str
    summary: str | None
    question: str | None
    branch: str | None
    head: str | None
    pr: str | None
    #: The run's last message: its question when `blocked`, else its report, so a channel can say what a reply answers.
    message: int | None
    #: The tickets the run filed that canopy recorded against the task, at most `MAX_FOLLOW_UPS`, in its result's order.
    tickets: list[str]


class ReplyRecorded(TypedDict):
    """A `reply.recorded` event's fields: a Slack mention of canopy recorded as the operator's message on a ticket."""

    ticket: str
    #: The operator message it recorded.
    message: int
    #: The Slack message's `ts`.
    ts: str
    body: str


class ReplyRefused(TypedDict):
    """A `reply.refused` event's fields: a reply read from Slack that canopy took nothing from, and why."""

    #: The ticket it named, or None for a mention that named none.
    ticket: str | None
    #: The Slack message's `ts`, which a sink answers under.
    ts: str
    #: The guard that refused it, as `canopy reply` names one, or `no_ticket`.
    guard: str
    reason: str


class LoopFailing(TypedDict):
    """A `loop.failing` event's fields."""

    count: int
    status: str
    tick: int
    log: str


class LoopRecovered(TypedDict):
    """A `loop.recovered` event's fields."""

    failed: int


class SinkFailing(TypedDict):
    """A `loop.sink_failing` event's fields."""

    sink: str
    error: str


class BudgetReached(TypedDict):
    """A `loop.budget_reached` event's fields: the local month's spend reached one of its alerts."""

    #: The month, `YYYY-MM`, in local time.
    month: str
    #: The budget, in whole US dollars.
    budget: int
    #: The alert reached, as a percentage of the budget: 100 for the budget itself.
    percent: int
    #: What the month's agent spend cost so far, canopy's runs and the sessions outside canopy, in US dollars,
    #: rounded to the cent.
    spent: float
    #: What the month will cost at this pace, in US dollars, rounded to the cent; None in its first day.
    projected: float | None
    #: Canopy's runs' part of `spent`, in US dollars, rounded to the cent.
    runs: float
    #: The sessions outside canopy's part of `spent`, in US dollars: `spent` less `runs`, so the parts add up to it; 0
    #: before any read.
    outside: float
    #: When `canopy loop` last read the runtime's sessions, a journal time; None when it never has.
    sessions_read_at: str | None
    #: How that read ended, a `SessionsRead`: after `failed`, `outside` is what an earlier read found; None when none
    #: ran.
    sessions_read: str | None


#: An example of each event's fields, by kind, for `canopy notify events`: what a sink's command reads.
EXAMPLES: Final[Mapping[str, Mapping[str, object]]] = {
    "run.started": RunStarted(
        ticket="PROJ-1",
        run=12,
        run_kind="implement",
        branch="canopy/PROJ-1",
        attempt=1,
        limit=3,
    ),
    "run.ended": RunEnded(
        ticket="PROJ-1",
        run=12,
        run_kind="implement",
        status="done",
        branch="canopy/PROJ-1",
        pr="https://github.example/acme/api/pull/7",
        prs=["https://github.example/acme/api/pull/7"],
        summary="Added the retry to the upload client.",
        question=None,
        message=40,
    ),
    "plan.proposed": PlanProposed(ticket="PROJ-1", run=11, plan=3),
    "plan.approved": PlanApproved(
        ticket="PROJ-1",
        run=11,
        plan=3,
        feedback=False,
        reason="One file, no new behavior.",
    ),
    "follow_ups.filed": FollowUpsFiled(ticket="PROJ-1", run=12, follow_ups={"PROJ-9": "api"}, count=1),
    "ci.flaky": CiFlaky(
        ticket="PROJ-1",
        run=13,
        prs=["https://github.example/acme/api/pull/7"],
        kicked=["api"],
        estimate="The upload test timed out on a slow runner.",
        cause="runner",
        other_cause=None,
        note=None,
    ),
    "epic.changed": EpicChanged(
        epic=2,
        plan=5,
        ids=["auth.login"],
        count=1,
        stale=["PROJ-4"],
        held=[],
        told=["PROJ-5"],
    ),
    "chore.ended": ChoreEnded(chore="deps", run=20, status="ok", summary="Two advisories, both filed.", findings=2),
    "chore.summary": ChoreSummary(
        chore="briefing",
        run=21,
        lines=["3 PRs wait on you.", "ana asked for changes on PROJ-1."],
    ),
    "review.ended": ReviewEnded(
        pr="https://github.example/acme/api/pull/7",
        repo="api",
        ticket="PROJ-1",
        run=30,
        status="done",
        verdict="findings",
        impact="low",
        findings=1,
    ),
    "task.ended": TaskEnded(
        task=4,
        run=31,
        status="done",
        summary="Bumped the base image.",
        question=None,
        branch="canopy/task-4",
        head="0123456789abcdef0123456789abcdef01234567",
        pr="https://github.example/acme/api/pull/7",
        message=41,
        tickets=[],
    ),
    "reply.recorded": ReplyRecorded(ticket="PROJ-1", message=42, ts="1790000000.000100", body="use the staging config"),
    "reply.refused": ReplyRefused(
        ticket=None,
        ts="1790000000.000200",
        guard="no_ticket",
        reason="the reply names no ticket",
    ),
    "loop.failing": LoopFailing(count=3, status="error", tick=88, log=".canopy/ticks/88.log"),
    "loop.recovered": LoopRecovered(failed=3),
    "loop.sink_failing": SinkFailing(sink="slack", error="exited 1: invalid_auth"),
    "loop.budget_reached": BudgetReached(
        month="2026-11",
        budget=300,
        percent=80,
        spent=241.5,
        projected=310.2,
        runs=200.0,
        outside=41.5,
        sessions_read_at="2026-11-16T09:00:00.000Z",
        sessions_read="found",
    ),
    "ci.kicked": CiKicked(
        ticket="PROJ-1",
        run=13,
        repo="api",
        branch="canopy/PROJ-1",
        pr="https://github.example/acme/api/pull/7",
        from_head="0123456789abcdef0123456789abcdef01234567",
        to_head="89abcdef0123456789abcdef0123456789abcdef",
        kick=1,
        limit=2,
    ),
}


def cut(text: object, limit: int) -> str:
    """One line of `text`, at most `limit` characters.

    Returns:
        `text` with its whitespace collapsed to single spaces, cut to `limit` characters ending in `...` if longer.
    """
    line = " ".join(str(text).split())
    return line if len(line) <= limit else line[: limit - len(_ELLIPSIS)] + _ELLIPSIS


def cut_lines(text: object, limit: int) -> list[str]:
    """The lines of `text`, at most `limit` characters in all, for a field that keeps its line breaks.

    Returns:
        Each line that is not blank, its whitespace collapsed to single spaces, until `limit` characters are used: the
        line that passes it is cut to what is left, ending in `...`, or left out when no more than `...` would fit.
    """
    found: list[str] = []
    left = limit
    for line in str(text).splitlines():
        flat = " ".join(line.split())
        if not flat:
            continue
        if len(flat) > left:
            if left > len(_ELLIPSIS):
                found.append(cut(flat, left))
            break
        found.append(flat)
        left -= len(flat)
    return found


def run_started(
    config: Config,
    *,
    key: str,
    kind: str,
    branch: str,
    attempt: int,
    limit: int,
) -> Callable[[int], Event | None]:
    """Return what builds a `run.started` event from the new run's id, for `db.insert_run`."""

    def build(run_id: int) -> Event | None:
        fields: RunStarted = {
            "ticket": key,
            "run": run_id,
            "run_kind": kind,
            "branch": branch,
            "attempt": attempt,
            "limit": limit,
        }
        return _taken(config, Event(RUNS, "run.started", fields))

    return build


def run_ended(
    config: Config,
    run: records.Run,
    status: RunStatus,
    result_json: str | None,
) -> Callable[[int | None], Event | None]:
    """Return what builds the `run.ended` event for a run closing as `status` with `result_json`.

    `db.finish_ticket_run` calls it once it knows the run's messages.

    It is built from the id of the message the run recorded (`message`): its question for a `blocked` run and its
    report otherwise, so a channel can say what a reply answers (DESIGN §22). It is None if no sink takes it.
    `question` is set only for a `blocked` run: a blocked worker waits on a label or a reply, not an attention item, so
    this is how a sink hears that it asked something.
    """

    def build(message: int | None) -> Event | None:
        result = contract.stored_object(result_json)
        prs = result.get("prs")
        pr = result.get("pr")
        pr_urls: list[str] = [str(u) for u in prs.values() if u] if isinstance(prs, dict) else []
        if not pr_urls and pr:
            pr_urls = [str(pr)]
        question = result.get("question") if status == RunStatus.BLOCKED else None
        summary = contract.stored_note(result)
        fields: RunEnded = {
            "ticket": run.ticket_key,
            "run": run.id,
            "run_kind": run.kind,
            "status": status,
            "branch": run.branch,
            "pr": cut(pr_urls[0], DETAIL_LIMIT) if pr_urls else None,
            "prs": [cut(u, DETAIL_LIMIT) for u in pr_urls],
            "summary": cut(summary, SUMMARY_LIMIT) if summary else None,
            "question": cut(question, SUMMARY_LIMIT) if question else None,
            "message": message,
        }
        return _taken(config, Event(RUNS, "run.ended", fields))

    return build


def plan_recorded(
    config: Config,
    *,
    key: str,
    run_id: int,
    feedback: bool = False,
) -> Callable[[int, str | None], Event | None]:
    """Return what builds a new plan's event from its id and its planner's approval, for `plans.record`.

    A plan that waits on the operator is `plan.proposed`, for a ticket's plan alone; one the harness approved on its
    planner's word, with the planner's reason, is `plan.approved`, for a feedback plan too, so the operator hears of it
    with nothing waiting on them (DESIGN §25). Each names the ticket, the run, and the plan, and no plan text, so
    nothing of the plan leaves the machine through a sink. It is None if no sink takes it.
    """

    def build(plan_id: int, reason: str | None) -> Event | None:
        if reason is not None:
            approved: PlanApproved = {
                "ticket": key,
                "run": run_id,
                "plan": plan_id,
                "feedback": feedback,
                "reason": cut(reason, SUMMARY_LIMIT),
            }
            return _taken(config, Event(RUNS, "plan.approved", approved))
        if feedback:
            return None
        fields: PlanProposed = {"ticket": key, "run": run_id, "plan": plan_id}
        return _taken(config, Event(RUNS, "plan.proposed", fields))

    return build


def epic_changed(
    config: Config,
) -> Callable[[records.EpicPlan, epic_outline.Change, epic_changes.Reached], Event | None]:
    """Return what builds the `epic.changed` event from the plan approved, its change, and whom it reached.

    `epics.approve` builds it once, in the approval's transaction, when the change reached a member: the operator's one
    word of which members it reached, each way (DESIGN §43). No plan text, so nothing of the plan leaves the machine
    through a sink. It is None if no sink takes it.
    """

    def build(plan: records.EpicPlan, change: epic_outline.Change, reached: epic_changes.Reached) -> Event | None:
        ids = epic_outline.ordered(change.ids())
        fields: EpicChanged = {
            "epic": plan.epic_id,
            "plan": plan.id,
            "ids": ids[:MAX_EPIC_IDS],
            "count": len(ids),
            "stale": list(reached.stale),
            "held": list(reached.held),
            "told": list(reached.told),
        }
        return _taken(config, Event(RUNS, "epic.changed", fields))

    return build


def follow_ups_filed(config: Config, *, key: str, run_id: int, filed: Mapping[str, str | None]) -> Event | None:
    """Return the `follow_ups.filed` event for the follow-ups run `run_id` of `key` filed, for the run's close.

    It is reported once, when the run records them, as a point event and not an attention item: a follow-up waits on
    nothing canopy watches, and the operator labels or starts the ones they want worked (DESIGN §18).

    Returns:
        The event, or None if no sink takes it or nothing was filed.
    """
    if not filed:
        return None
    fields: FollowUpsFiled = {
        "ticket": key,
        "run": run_id,
        "follow_ups": dict(list(filed.items())[:MAX_FOLLOW_UPS]),
        "count": len(filed),
    }
    return _taken(config, Event(RUNS, "follow_ups.filed", fields))


def ci_flaky(
    config: Config,
    *,
    key: str,
    run_id: int,
    prs: Sequence[str],
    kicked: Sequence[str],
    estimate: str,
    cause: str | None,
    other_cause: str | None,
    note: str,
) -> Event | None:
    """Return the `ci.flaky` event for run `run_id` of `key`, which left a failed check as flaky, for the run's close.

    It is a point event, kicked or not: a kicked check reruns on its own, and one that is not raises `flaky_rerun`
    once the overseer reads it (DESIGN §23), so the sink hears the worker's estimate of why either way.

    Returns:
        The event, or None if no sink takes it.
    """
    fields: CiFlaky = {
        "ticket": key,
        "run": run_id,
        "prs": [cut(pr, DETAIL_LIMIT) for pr in prs],
        "kicked": list(kicked),
        "estimate": cut(estimate, DETAIL_LIMIT),
        "cause": cause,
        "other_cause": cut(other_cause, DETAIL_LIMIT) if other_cause else None,
        "note": cut(note, DETAIL_LIMIT) if note else None,
    }
    return _taken(config, Event(RUNS, "ci.flaky", fields))


def ci_kicked(
    config: Config,
    *,
    key: str,
    run_id: int,
    repo: str,
    branch: str,
    pr: str | None,
    from_head: str,
    to_head: str,
    kick: int,
    limit: int,
) -> Event | None:
    """Return the `ci.kicked` event for a forced push run `run_id` of `key` made to `branch` in `repo`, once it is made.

    Returns:
        The event, or None if no sink takes it.
    """
    fields: CiKicked = {
        "ticket": key,
        "run": run_id,
        "repo": repo,
        "branch": branch,
        "pr": cut(pr, DETAIL_LIMIT) if pr else None,
        "from_head": from_head,
        "to_head": to_head,
        "kick": kick,
        "limit": limit,
    }
    return _taken(config, Event(LOOP, "ci.kicked", fields))


def chore_ended(
    config: Config,
    chore: str,
    run_id: int,
    status: ChoreRunStatus,
    result_json: str | None,
) -> Event | None:
    """Return the `chore.ended` event for run `run_id` of `chore`, or None if no sink takes it.

    A summary `chore_summary` sends whole is left off it: status and output are separate events, so a sink can take
    one without the other.
    """
    result = contract.stored_object(result_json)
    findings = result.get("findings")
    summary = contract.stored_note(result)
    fields: ChoreEnded = {
        "chore": chore,
        "run": run_id,
        "status": status,
        "summary": cut(summary, SUMMARY_LIMIT) if summary and not _whole_summary(config, chore, result) else None,
        "findings": len(findings) if isinstance(findings, list) else 0,
    }
    return _taken(config, Event(CHORES, "chore.ended", fields))


def chore_summary(config: Config, chore: str, run_id: int, result_json: str | None) -> Event | None:
    """Return the `chore.summary` event for run `run_id` of `chore`, recorded with its `chore.ended`.

    Returns:
        The event, or None unless the chore's table sets `whole_summary`, the run's result holds its summary, and some
        sink takes it. A harness note, such as a crash's, is the run's status, not its output, so it sends none.
    """
    summary = _whole_summary(config, chore, contract.stored_object(result_json))
    if summary is None:
        return None
    fields: ChoreSummary = {"chore": chore, "run": run_id, "lines": cut_lines(summary, chore_result.MAX_SUMMARY)}
    return _taken(config, Event(CHORES, "chore.summary", fields))


def review_ended(
    config: Config,
    run: records.ReviewRun,
    status: ReviewRunStatus,
    result_json: str | None,
    *,
    repo: str | None,
) -> Event | None:
    """Return the `review.ended` event for a review run in `repo`, or None if no sink takes it, or for a revision.

    A revision of a review's draft (DESIGN §34) reports no verdict, and the operator who asked for it reads its version
    in canopy.
    """
    if run.revises is not None:
        return None
    result = review_result.stored(result_json)
    fields: ReviewEnded = {
        "pr": run.pr_url,
        "repo": repo,
        "ticket": run.ticket_key,
        "run": run.id,
        "status": status,
        "verdict": result.verdict if result is not None else None,
        "impact": result.impact if result is not None else None,
        # How many, not what: the findings stay in the journal (D114).
        "findings": len(result.findings) if result is not None else 0,
    }
    return _taken(config, Event(REVIEWS, "review.ended", fields))


def task_ended(
    config: Config,
    run: records.TaskRun,
    status: RunStatus,
    result_json: str | None,
    *,
    head: str | None,
    message: int | None,
    tickets: Sequence[str] = (),
) -> Event | None:
    """Return the `task.ended` event for task run `run`, closing as `status` with `head` on origin, or None.

    `tickets` are the keys the run's close recorded against the task (DESIGN §36).

    It is None unless a sink takes it, which none does unless the operator lists `tasks`: a task's work is private, and
    a sink's audience may not be (DESIGN §36).
    """
    result = contract.stored_object(result_json)
    summary = contract.stored_note(result)
    question = result.get("question") if status == RunStatus.BLOCKED else None
    prs = result.get("prs")
    listed: list[object] = prs if isinstance(prs, list) else []
    urls = [u for u in listed if isinstance(u, str) and u]
    fields: TaskEnded = {
        "task": run.task_id,
        "run": run.id,
        "status": status,
        "summary": cut(summary, SUMMARY_LIMIT) if summary else None,
        "question": cut(question, SUMMARY_LIMIT) if question else None,
        "branch": run.branch if head else None,
        "head": head,
        "pr": cut(urls[0], DETAIL_LIMIT) if urls else None,
        "message": message,
        "tickets": list(tickets[:MAX_FOLLOW_UPS]),
    }
    return _taken(config, Event(TASKS, "task.ended", fields))


def reply_recorded(config: Config, *, key: str, ts: str, body: str) -> Callable[[int], Event | None]:
    """Return what builds a `reply.recorded` event from the operator message's id, for `conversation.reply`."""

    def build(message: int) -> Event | None:
        fields: ReplyRecorded = {"ticket": key, "message": message, "ts": ts, "body": cut(body, SUMMARY_LIMIT)}
        return _taken(config, Event(REPLIES, "reply.recorded", fields))

    return build


def reply_refused(config: Config, *, key: str | None, ts: str, guard: str, reason: str) -> Event | None:
    """A `reply.refused` event, or None if no sink takes it.

    Returns:
        The event.
    """
    fields: ReplyRefused = {"ticket": key, "ts": ts, "guard": guard, "reason": cut(reason, DETAIL_LIMIT)}
    return _taken(config, Event(REPLIES, "reply.refused", fields))


def loop_failing(count: int, status: str, tick_id: int, log: str) -> Event:
    """The latest ticks all ended other than `ok`.

    Returns:
        The `loop.failing` event, naming how many ticks failed, the latest one's status and id, and the log.
    """
    fields: LoopFailing = {"count": count, "status": status, "tick": tick_id, "log": log}
    return Event(LOOP, "loop.failing", fields)


def loop_recovered(failed: int) -> Event:
    """The first `ok` tick after `loop.failing`.

    Returns:
        The `loop.recovered` event, naming how many ticks had failed.
    """
    fields: LoopRecovered = {"failed": failed}
    return Event(LOOP, "loop.recovered", fields)


def sink_failing(sink: str, error: str) -> Event:
    """A sink has failed its latest deliveries in a row.

    Returns:
        The `loop.sink_failing` event, naming the sink and its latest error.
    """
    fields: SinkFailing = {"sink": sink, "error": cut(error, DETAIL_LIMIT)}
    return Event(LOOP, "loop.sink_failing", fields)


def budget_reached(month: spend.Month, percent: int) -> Event:
    """The local month's spend reached `percent` of the operator's monthly budget.

    Returns:
        The `loop.budget_reached` event, naming the month, the budget, the alert, what it spent, canopy's part and the
        part outside canopy, when the runtime's sessions were last read, and where it is headed.
    """
    # The parts are taken from the rounded whole, so a sink never shows them a cent apart from it.
    spent, runs = round(month.spent_usd or 0.0, 2), round(month.runs_usd or 0.0, 2)
    fields: BudgetReached = {
        "month": month.month,
        "budget": month.budget_usd,
        "percent": percent,
        "spent": spent,
        "projected": round(month.projected_usd, 2) if month.projected_usd is not None else None,
        "runs": runs,
        "outside": round(spent - runs, 2),
        "sessions_read_at": month.sessions_read_at,
        "sessions_read": month.sessions_read.value if month.sessions_read is not None else None,
    }
    return Event(LOOP, BUDGET_REACHED, fields)


def _taken(config: Config, event: Event) -> Event | None:
    """Return `event` if some sink takes its name, else None: an event no sink takes is not recorded."""
    return event if config.notify.takes(event.name) else None


def _whole_summary(config: Config, chore: str, result: Mapping[str, object]) -> str | None:
    """The agent's summary in `result`, when `chore`'s table sends it whole (`whole_summary`) and it has one.

    Returns:
        The summary, not cut, or None.
    """
    table = config.chores.get(chore)
    if table is None or not table.whole_summary or result.get("harness"):
        return None
    summary = contract.stored_note(result)
    return summary or None
