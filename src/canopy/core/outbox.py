"""The events notification sinks receive (DESIGN §20): a closed set, built here from what the harness already knows.

Dispatch, `_run`, `_chore`, and reconcile record them through `canopy.core.db` in the transaction that records the fact;
the `canopy.notify` feature delivers them. An event is built only when some sink takes its group, so with no sinks no
event is recorded. Text fields are cut to the limits DESIGN §20 lists and kept to one line.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import TYPE_CHECKING, TypedDict

from canopy.core import contract, review_result
from canopy.core.db import Event

if TYPE_CHECKING:
    from canopy.core.config import Config
    from canopy.core.vocab import ChoreRunStatus, ReviewRunStatus, RunStatus

RUNS = "runs"
LOOP = "loop"
CHORES = "chores"
REVIEWS = "reviews"
SUMMARY_LIMIT = 300
DETAIL_LIMIT = 500


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
    config: Config, *, key: str, kind: str, branch: str, attempt: int, limit: int
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
    config: Config, run: sqlite3.Row, status: RunStatus, result_json: str | None
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


def chore_ended(
    config: Config, chore: str, run_id: int, status: ChoreRunStatus, result_json: str | None
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


def review_ended(config: Config, run: sqlite3.Row, status: ReviewRunStatus, result_json: str | None) -> Event | None:
    """Return the `review.ended` event for a review run, or None if no sink takes reviews."""
    if not config.notify.takes(REVIEWS):
        return None
    result = review_result.stored(result_json)
    fields: ReviewEnded = {
        "pr": run["pr_url"],
        "ticket": run["ticket_key"],
        "run": run["id"],
        "status": status,
        "verdict": result.verdict if result is not None else None,
        "impact": result.impact if result is not None else None,
        # How many, not what: the findings stay in the journal (D114).
        "findings": len(result.findings) if result is not None else 0,
    }
    return Event(REVIEWS, "review.ended", fields)


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
