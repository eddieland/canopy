"""The events notification sinks receive (DESIGN §20): a closed set, built here from what the harness already knows.

Dispatch, `_run`, `_chore`, and reconcile record them through `canopy.core.db` in the transaction that records the fact;
the `canopy.notify` feature delivers them. An event is built only when some sink takes its group, so with no sinks no
event is recorded. Text fields are cut to the limits DESIGN §20 lists and kept to one line.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, TypedDict

from canopy.core import contract, review_result
from canopy.core.db import Event

if TYPE_CHECKING:
    from canopy.core import records
    from canopy.core.config import Config
    from canopy.core.vocab import ChoreRunStatus, ReviewRunStatus, RunStatus

RUNS = "runs"
LOOP = "loop"
CHORES = "chores"
REVIEWS = "reviews"
#: A one-off task's runs (DESIGN §36): a group of its own, which no sink takes unless the operator lists it.
TASKS = "tasks"
SUMMARY_LIMIT = 300
DETAIL_LIMIT = 500
#: How many follow-ups a `follow_ups.filed` event names; the rest are counted.
MAX_FOLLOW_UPS = 20


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


class FollowUpsFiled(TypedDict):
    """A `follow_ups.filed` event's fields: the follow-ups one run filed, each with its repository or null (§18).

    `follow_ups` names at most `MAX_FOLLOW_UPS`; `count` is how many the run filed.
    """

    ticket: str
    run: int
    follow_ups: dict[str, str | None]
    count: int


class ChoreEnded(TypedDict):
    """A `chore.ended` event's fields."""

    chore: str
    run: int
    status: str
    summary: str | None
    findings: int


class ReviewEnded(TypedDict):
    """A `review.ended` event's fields: how many findings, never what they are (D114)."""

    pr: str
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


def cut(text: object, limit: int) -> str:
    """One line of `text`, at most `limit` characters.

    Returns:
        `text` with its whitespace collapsed to single spaces, cut to `limit` characters ending in `...` if longer.
    """
    line = " ".join(str(text).split())
    return line if len(line) <= limit else line[: limit - 3] + "..."


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
        if not config.notify.takes(RUNS):
            return None
        fields: RunStarted = {
            "ticket": key,
            "run": run_id,
            "run_kind": kind,
            "branch": branch,
            "attempt": attempt,
            "limit": limit,
        }
        return Event(RUNS, "run.started", fields)

    return build


def run_ended(
    config: Config,
    run: sqlite3.Row,
    status: RunStatus,
    result_json: str | None,
) -> Callable[[int | None], Event | None]:
    """Return what builds the `run.ended` event for a run closing as `status` with `result_json`.

    `db.finish_ticket_run` calls it once it knows the run's messages.

    It is built from the id of the message the run recorded (`message`): its question for a `blocked` run and its
    report otherwise, so a channel can say what a reply answers (DESIGN §22). It is None if no sink takes runs.
    `question` is set only for a `blocked` run: a blocked worker waits on a label or a reply, not an attention item, so
    this is how a sink hears that it asked something.
    """

    def build(message: int | None) -> Event | None:
        if not config.notify.takes(RUNS):
            return None
        result = contract.stored_object(result_json)
        prs = result.get("prs")
        pr = result.get("pr")
        pr_urls: list[str] = [str(u) for u in prs.values() if u] if isinstance(prs, dict) else []
        if not pr_urls and pr:
            pr_urls = [str(pr)]
        question = result.get("question") if status == "blocked" else None
        summary = contract.stored_note(result)
        fields: RunEnded = {
            "ticket": run["ticket_key"],
            "run": run["id"],
            "run_kind": run["kind"],
            "status": status,
            "branch": run["branch"],
            "pr": cut(pr_urls[0], DETAIL_LIMIT) if pr_urls else None,
            "prs": [cut(u, DETAIL_LIMIT) for u in pr_urls],
            "summary": cut(summary, SUMMARY_LIMIT) if summary else None,
            "question": cut(question, SUMMARY_LIMIT) if question else None,
            "message": message,
        }
        return Event(RUNS, "run.ended", fields)

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
    nothing of the plan leaves the machine through a sink. It is None if no sink takes runs.
    """

    def build(plan_id: int, reason: str | None) -> Event | None:
        if not config.notify.takes(RUNS):
            return None
        if reason is not None:
            approved: PlanApproved = {
                "ticket": key,
                "run": run_id,
                "plan": plan_id,
                "feedback": feedback,
                "reason": cut(reason, SUMMARY_LIMIT),
            }
            return Event(RUNS, "plan.approved", approved)
        if feedback:
            return None
        fields: PlanProposed = {"ticket": key, "run": run_id, "plan": plan_id}
        return Event(RUNS, "plan.proposed", fields)

    return build


def follow_ups_filed(config: Config, *, key: str, run_id: int, filed: Mapping[str, str | None]) -> Event | None:
    """Return the `follow_ups.filed` event for the follow-ups run `run_id` of `key` filed, for the run's close.

    It is reported once, when the run records them, as a point event and not an attention item: a follow-up waits on
    nothing canopy watches, and the operator labels or starts the ones they want worked (DESIGN §18).

    Returns:
        The event, or None if no sink takes runs or nothing was filed.
    """
    if not filed or not config.notify.takes(RUNS):
        return None
    fields: FollowUpsFiled = {
        "ticket": key,
        "run": run_id,
        "follow_ups": dict(list(filed.items())[:MAX_FOLLOW_UPS]),
        "count": len(filed),
    }
    return Event(RUNS, "follow_ups.filed", fields)


def chore_ended(
    config: Config,
    chore: str,
    run_id: int,
    status: ChoreRunStatus,
    result_json: str | None,
) -> Event | None:
    """Return the `chore.ended` event for run `run_id` of `chore`, or None if no sink takes chores."""
    if not config.notify.takes(CHORES):
        return None
    result = contract.stored_object(result_json)
    findings = result.get("findings")
    summary = contract.stored_note(result)
    fields: ChoreEnded = {
        "chore": chore,
        "run": run_id,
        "status": status,
        "summary": cut(summary, SUMMARY_LIMIT) if summary else None,
        "findings": len(findings) if isinstance(findings, list) else 0,
    }
    return Event(CHORES, "chore.ended", fields)


def review_ended(
    config: Config,
    run: records.ReviewRun,
    status: ReviewRunStatus,
    result_json: str | None,
) -> Event | None:
    """Return the `review.ended` event for a review run, or None if no sink takes reviews, or for a revision.

    A revision of a review's draft (DESIGN §34) reports no verdict, and the operator who asked for it reads its version
    in canopy.
    """
    if not config.notify.takes(REVIEWS) or run.revises is not None:
        return None
    result = review_result.stored(result_json)
    fields: ReviewEnded = {
        "pr": run.pr_url,
        "ticket": run.ticket_key,
        "run": run.id,
        "status": status,
        "verdict": result.verdict if result is not None else None,
        "impact": result.impact if result is not None else None,
        # How many, not what: the findings stay in the journal (D114).
        "findings": len(result.findings) if result is not None else 0,
    }
    return Event(REVIEWS, "review.ended", fields)


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

    It is None unless a sink takes `tasks`: a task's work is private, and a sink's audience may not be (DESIGN §36).
    """
    if not config.notify.takes(TASKS):
        return None
    result = contract.stored_object(result_json)
    summary = contract.stored_note(result)
    question = result.get("question") if status == "blocked" else None
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
    return Event(TASKS, "task.ended", fields)


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
