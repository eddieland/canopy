"""The events notification sinks receive (DESIGN §20): a closed set, built here from what the harness already knows.

Dispatch, `_run`, `_chore`, and reconcile record them through `canopy.core.db` in the transaction that records the fact;
the `canopy.notify` feature delivers them. An event is built only when some sink takes its group, so with no sinks no
event is recorded. Text fields are cut to the limits DESIGN §20 lists and kept to one line.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from canopy.core.db import Event

if TYPE_CHECKING:
    from canopy.core.config import Config

RUNS = "runs"
LOOP = "loop"
CHORES = "chores"
REVIEWS = "reviews"
SUMMARY_LIMIT = 300
DETAIL_LIMIT = 500


def cut(text: object, limit: int) -> str:
    """One line of `text`, at most `limit` characters."""
    line = " ".join(str(text).split())
    return line if len(line) <= limit else line[: limit - 3] + "..."


def run_started(
    config: Config, *, key: str, kind: str, branch: str, attempt: int, limit: int
) -> Callable[[int], Event | None]:
    """Return what builds a `run.started` event from the new run's id, for `db.insert_run`."""

    def build(run_id: int) -> Event | None:
        if not config.notify.takes(RUNS):
            return None
        fields = {"ticket": key, "run": run_id, "run_kind": kind, "branch": branch, "attempt": attempt, "limit": limit}
        return Event(RUNS, "run.started", fields)

    return build


def run_ended(config: Config, run: sqlite3.Row, status: str, result_json: str | None) -> Event | None:
    """Return the `run.ended` event for a run closing as `status` with `result_json`, or None if no sink takes runs.

    `question` is set only for a `blocked` run: a blocked worker waits on a label, not an attention item, so this is how
    a sink hears that it asked something.
    """
    if not config.notify.takes(RUNS):
        return None
    result = _object(result_json)
    prs = result.get("prs")
    pr = result.get("pr")
    pr_urls: list[str] = [str(u) for u in prs.values() if u] if isinstance(prs, dict) else []
    if not pr_urls and pr:
        pr_urls = [str(pr)]
    question = result.get("question") if status == "blocked" else None
    summary = result.get("harness") or result.get("summary")
    fields: dict[str, object] = {
        "ticket": run["ticket_key"],
        "run": run["id"],
        "run_kind": run["kind"],
        "status": status,
        "branch": run["branch"],
        "pr": cut(pr_urls[0], DETAIL_LIMIT) if pr_urls else None,
        "prs": [cut(u, DETAIL_LIMIT) for u in pr_urls],
        "summary": cut(summary, SUMMARY_LIMIT) if summary else None,
        "question": cut(question, SUMMARY_LIMIT) if question else None,
    }
    return Event(RUNS, "run.ended", fields)


def chore_ended(config: Config, run: sqlite3.Row, status: str, result_json: str | None) -> Event | None:
    """Return the `chore.ended` event for a chore run, or None if no sink takes chores."""
    if not config.notify.takes(CHORES):
        return None
    result = _object(result_json)
    findings = result.get("findings")
    summary = result.get("harness") or result.get("summary")
    fields: dict[str, object] = {
        "chore": run["chore"],
        "run": run["id"],
        "status": status,
        "summary": cut(summary, SUMMARY_LIMIT) if summary else None,
        "findings": len(findings) if isinstance(findings, list) else 0,
    }
    return Event(CHORES, "chore.ended", fields)


def review_ended(config: Config, run: sqlite3.Row, status: str, result_json: str | None) -> Event | None:
    """Return the `review.ended` event for a review run, or None if no sink takes reviews."""
    if not config.notify.takes(REVIEWS):
        return None
    result = _object(result_json)
    fields: dict[str, object] = {
        "pr": run["pr_url"],
        "ticket": run["ticket_key"],
        "run": run["id"],
        "status": status,
        "verdict": result.get("verdict"),
        "impact": result.get("impact"),
        "comment": cut(result["comment"], DETAIL_LIMIT) if result.get("comment") else None,
    }
    return Event(REVIEWS, "review.ended", fields)


def loop_failing(count: int, status: str, tick_id: int, log: str) -> Event:
    """The latest ticks all ended other than `ok`."""
    return Event(LOOP, "loop.failing", {"count": count, "status": status, "tick": tick_id, "log": log})


def loop_recovered(failed: int) -> Event:
    """The first `ok` tick after `loop.failing`."""
    return Event(LOOP, "loop.recovered", {"failed": failed})


def sink_failing(sink: str, error: str) -> Event:
    """A sink has failed its latest deliveries in a row."""
    return Event(LOOP, "loop.sink_failing", {"sink": sink, "error": cut(error, DETAIL_LIMIT)})


def _object(result_json: str | None) -> Mapping[str, object]:
    if not result_json:
        return {}
    try:
        parsed: object = json.loads(result_json)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): v for k, v in parsed.items()}
