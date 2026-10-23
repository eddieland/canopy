"""canopy's read-only reports as an agent reads them, one JSON object each: health, spend, and agent memory.

`canopy health --json`, `canopy spend --json`, and `canopy memory lessons`, `proposals`, and `list` with `--json` print
them, and a chore's run reads them through tools of the same names, `canopy_chore_health` and so on, which `canopy _mcp
--chore` serves (DESIGN §27). Both build a request here and call its function, in the style of the overseer's verbs
(`loop.tools`), so a tool and its command take the same bounds and say the same text. None of them writes.

What a worker wrote, a memory's text, is printed with every character that hides text named, as the listings print it.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from canopy.core import config, conversation, db, health, memory, memory_manage, spend
from canopy.core.memory_text import quoted

if TYPE_CHECKING:
    from collections.abc import Mapping

    from canopy.core import records
    from canopy.core.context import Context

#: The tools a chore's server serves of these, by their own names: each command's, with hyphens for spaces.
HEALTH = "health"
SPEND = "spend"
MEMORY_LESSONS = "memory-lessons"
MEMORY_PROPOSALS = "memory-proposals"
MEMORY_LIST = "memory-list"
TOOLS = (HEALTH, SPEND, MEMORY_LESSONS, MEMORY_PROPOSALS, MEMORY_LIST)


def _repo(value: str) -> str:
    if not config.REPO_NAME_RE.fullmatch(value):
        raise ValueError(f"invalid repository name {value!r}: must match {config.REPO_NAME_RE.pattern}")
    return value


def _key(value: str) -> str:
    if not conversation.KEY_RE.fullmatch(value):
        raise ValueError(f"invalid ticket key {value!r}: must match {conversation.KEY_RE.pattern}")
    return value


#: How many local days a report reads, today's so far included.
Days = Annotated[
    StrictInt,
    Field(ge=1, le=spend.MAX_DAYS, description="How many local days to read, today's so far included."),
]


class Request(BaseModel):
    """What every report takes: an unknown field is refused, as the overseer's requests refuse one."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)


class Health(Request):
    """`health`: how the ticks and runs of the last days ended, the newest failures, and what the guards refused."""

    #: The days to read.
    days: Days = spend.DEFAULT_DAYS


class Spend(Request):
    """`spend`: what agent runs cost over the last days, by kind, ticket, tool, and model."""

    #: The days to read.
    days: Days = spend.DEFAULT_DAYS


class MemoryLessons(Request):
    """`memory-lessons`: the lessons the operator promoted, each with its reads, citations, and any wrong report."""

    #: Only the lessons a run in this repository is served.
    repo: Annotated[
        Annotated[StrictStr, AfterValidator(_repo)] | None,
        Field(
            max_length=64,
            description="Only the lessons a run in this repository is served: its own and every one's.",
        ),
    ] = None


class MemoryProposals(Request):
    """`memory-proposals`: the lessons workers proposed that wait on the operator, each with where it came from."""


class MemoryList(Request):
    """`memory-list`: the ticket notes workers recorded, of one ticket or of every one."""

    #: Only this ticket's notes.
    key: Annotated[
        Annotated[StrictStr, AfterValidator(_key)] | None,
        Field(max_length=100, description="Only this ticket's notes, by its key."),
    ] = None
    #: Superseded and invalid notes, and tombstones, too.
    all: Annotated[StrictBool, Field(description="Also list superseded and invalid notes, and tombstones.")] = False


def read_health(ctx: Context, request: Health) -> str:
    """Report how the last `request.days` days' ticks and runs ended, as `canopy health --json` prints it.

    Returns:
        The report's JSON.
    """
    return report_json(dataclasses.asdict(health.report(ctx.conn, datetime.now(UTC), request.days)))


def read_spend(ctx: Context, request: Spend) -> str:
    """Report what the last `request.days` days' agent runs cost, as `canopy spend --json` prints it.

    Returns:
        The breakdown's JSON.
    """
    return report_json(spend_dict(spend.breakdown(ctx.conn, datetime.now(UTC), request.days)))


def read_lessons(ctx: Context, request: MemoryLessons) -> str:
    """List the lessons in force, of `request.repo` if it names one, as `canopy memory lessons --json` prints them.

    Returns:
        The tiers' modes and the lessons, as JSON.
    """
    lessons = [m for m in memory.active_lessons(ctx.conn) if request.repo is None or m.repo in (None, request.repo)]
    seen = memory.reads(ctx.conn, [m.id for m in lessons])
    return report_json({"modes": _modes(ctx), "lessons": [_lesson_json(ctx, m, read_of(seen, m)) for m in lessons]})


def read_proposals(ctx: Context, request: MemoryProposals) -> str:  # noqa: ARG001  (a listing takes no field)
    """List the proposals that wait on the operator, as `canopy memory proposals --json` prints them.

    Returns:
        The tiers' modes and the proposals, as JSON.
    """
    waiting = memory.pending_proposals(ctx.conn)
    return report_json({"modes": _modes(ctx), "proposals": [_proposal_json(ctx, p) for p in waiting]})


def read_notes(ctx: Context, request: MemoryList) -> str:
    """List the ticket notes, of `request.key` if it names one, as `canopy memory list --json` prints them.

    Returns:
        The tiers' modes and the notes, as JSON.
    """
    found = memory.notes(ctx.conn, request.key, every=request.all)
    seen = memory.reads(ctx.conn, [n.id for n in found])
    return report_json({"modes": _modes(ctx), "notes": [_note_json(n, read_of(seen, n)) for n in found]})


def report_json(report: dict[str, Any]) -> str:
    """A report as `--json` prints it: one JSON object, with each value on a line of its own.

    An agent reads a long report from the file its runtime saves it to, through file tools that cut a line at a few
    thousand characters, so a report on one line is cut short. A line for each value keeps all of it readable for about
    2% more than the compact form, where indenting by two costs a third to a half more.

    Returns:
        The JSON text, its keys sorted.
    """
    return json.dumps(report, sort_keys=True, indent=0)


def spend_dict(found: spend.Breakdown) -> dict[str, Any]:
    """A spend breakdown as JSON-ready values, each set of costs with its total.

    Returns:
        A dict `json.dumps` takes as it is.
    """
    data = dataclasses.asdict(found)
    for day, row in zip(data["per_day"], found.per_day, strict=True):
        day["costs"]["total"] = row.costs.total
    data["totals"]["total"] = found.totals.total
    return data


def read_of(seen: Mapping[int, memory.Reads], entry: records.Memory) -> memory.Reads:
    """What `memory.reads` found of `entry`, or no reads if it found none.

    Returns:
        Its reads.
    """
    return seen.get(entry.id, memory.Reads())


def _modes(ctx: Context) -> dict[str, str]:
    """Each tier's mode, by its key under `[memory]`, as the listings print it.

    Returns:
        `ticket_notes` and `proposals`, each `off`, `record`, or `use`.
    """
    settings = ctx.config.memory
    return {"ticket_notes": settings.ticket_notes, "proposals": settings.proposals}


def _lesson_json(ctx: Context, lesson: records.Memory, read: memory.Reads) -> dict[str, Any]:
    """A lesson as `memory lessons --json` prints it, with what it was made from.

    Its reads and citations are counted as a note's are (`_note_json`).

    Returns:
        The lesson's fields.
    """
    source = memory.origin(ctx.conn, lesson)
    return {
        "id": lesson.id,
        "key": lesson.key,
        "repo": lesson.repo,
        "made": "edited" if memory.edited(lesson) else "promoted",
        "approved_at": lesson.approved_at,
        "from": None
        if source is None
        else {"scope": source.scope, "id": source.id, "ticket": source.ticket_key, "run_id": source.run_id},
        "review_at": lesson.review_at,
        "pinned_at": lesson.pinned_at,
        "read_count": read.count,
        "last_read_at": read.last_at,
        "use_count": lesson.use_count,
        "last_used_at": lesson.last_used_at,
        "wrong_at": lesson.wrong_at,
        "wrong_run_id": lesson.wrong_run_id,
        "text": _text(lesson),
    }


def _text(entry: records.Memory) -> str | None:
    """A memory's text with every character that hides text named, or None once it is forgotten.

    Returns:
        The text, or None.
    """
    return quoted(entry.body, "") if entry.body is not None else None


def _proposal_json(ctx: Context, p: records.Memory) -> dict[str, Any]:
    """A proposal as `memory proposals --json` prints it, with its run and whether its ticket is done.

    Returns:
        The proposal's fields.
    """
    run = db.get_run(ctx.conn, p.run_id) if p.run_id is not None else None
    ticket = db.get_ticket(ctx.conn, p.ticket_key) if p.ticket_key is not None else None
    return {
        "id": p.id,
        "key": p.key,
        "repo": p.repo,
        "ticket": p.ticket_key,
        "run_id": p.run_id,
        "run_kind": run["kind"] if run is not None else None,
        "run_status": run["status"] if run is not None else None,
        "private": memory_manage.from_private_run(ctx.conn, p),
        "ticket_done": ticket is not None and ticket.done,
        "created_at": p.created_at,
        "text": _text(p),
    }


def _note_json(note: records.Memory, read: memory.Reads) -> dict[str, Any]:
    """A ticket note as `memory list --json` prints it: `run_id` null for one the operator wrote.

    `read_count` counts the runs whose prompts carried it; `use_count` only the runs that cited it in `memory_used`.

    Returns:
        The note's fields.
    """
    return {
        "id": note.id,
        "ticket": note.ticket_key,
        "key": note.key,
        "status": note.status,
        "why": note.why,
        "run_id": note.run_id,
        "created_at": note.created_at,
        "read_count": read.count,
        "last_read_at": read.last_at,
        "use_count": note.use_count,
        "last_used_at": note.last_used_at,
        "text": _text(note),
    }
