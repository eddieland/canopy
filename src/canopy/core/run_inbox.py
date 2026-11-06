"""The operator's messages to a running worker's, planner's, or one-off task's run, told and fetched (DESIGN §44).

A message to a running run is an operator message on the run's subject, its ticket or its task, as any reply is
(`conversation.reply`, DESIGN §22), naming the run it was sent to. canopy writes it to the run's answers directory
(§41), which a sandboxed run may read and not write (§24), as two files: the messages themselves, which canopy's
`messages` tool reads for the agent, and a mark, the newest message's id and nothing of its text, which canopy's plugin
reads after each tool call to tell the agent, once per message per session, that a message waits and which tool returns
it (`.agents/plugins/canopy.js`). So no `[canopy]` line carries the operator's words, and a forged line can only make
the agent spend a call to learn that nothing is new (TRUST_MODEL T1).

The tool is served beside `status` by the run's own server (`canopy _mcp --status`), which opens no workspace: a
sandboxed run, and the servers it starts, may not read the journal, so the tool reads the file canopy wrote. The harness
records the fetch from the call in the events it already reads (§8): a message canopy wrote before the call started was
in the file the call read, so it is fetched; one written while the call ran may not have been, so it waits for the next.

A message the run fetched is answered once that run ends with its report, `done` or `blocked`, which says what it did
with it, and the loop reads past it (`HEARD`). One never fetched, or fetched by a run that then failed, timed out,
crashed, or was stopped, stays an operator message like any other, so the next run's prompt carries it.

An unsandboxed run could write the answers directory, as it could any of the operator's files, and so make its own tool
return what it wrote; nothing a file, a PR, or a tool's result says can.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, assert_never

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, ValidationError

from canopy.core import cards, db, records, sql
from canopy.core.vocab import RunStatus
from canopy.infra.text import printable, quoted
from canopy.runtime import servers

if TYPE_CHECKING:
    import sqlite3

    from canopy.runtime.report import Called

#: The tool, served by the run's own server beside `status`: the agent sees it as `canopy_run_messages`.
TOOL = "messages"
#: The file in a run's answers directory that holds the messages sent to it, which the tool reads, and the file that
#: marks the newest of them by its id alone, which canopy's plugin reads.
TEXTS_FILE = "messages.json"
MARK_FILE = "message.json"
#: How many messages one run may be sent: each is at most `conversation.MAX_OPERATOR` characters, so the tool's result,
#: which carries them all, stays bounded.
MAX_MESSAGES = 20
#: A run's CANOPY_RUN_ID that names a run that takes messages: a worker's or a planner's id, or a task's, `task-3`. A
#: review's, `review-7`, takes none (DESIGN §44, Open).
RUN_ID_RE = re.compile(r"(?:task-)?[0-9]{1,18}")
#: The run tables whose running runs take messages, and the column of `messages` that names the run each was sent to.
type MessageTable = Literal["runs", "task_runs"]
_TO: Mapping[MessageTable, Literal["to_run_id", "to_task_run_id"]] = {
    "runs": "to_run_id",
    "task_runs": "to_task_run_id",
}
#: The statuses a run's report ends it with, `done` and `blocked`: such a run says what it did with what it fetched.
_REPORTED = (RunStatus.DONE, RunStatus.BLOCKED)
#: The ids of the messages a run fetched and then reported on: answered, so the loop reads past them, as it reads past
#: an operator message its cursor has passed. Every other message to a run stays the operator's word to its subject.
HEARD = sql.frag(
    "SELECT h.id FROM messages h WHERE h.fetched_at IS NOT NULL AND ("
    "h.to_run_id IN (SELECT r.id FROM runs r WHERE r.status IN (?, ?))"
    " OR h.to_task_run_id IN (SELECT t.id FROM task_runs t WHERE t.status IN (?, ?)))",
    *_REPORTED,
    *_REPORTED,
)


class Request(BaseModel):
    """The `messages` tool's arguments: none. It returns every message sent to this run."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)


@dataclass(frozen=True)
class Delivered:
    """A message as the run's agent reads it: its id, when the operator sent it, and its text."""

    id: int
    at: str
    text: str


def tool_name() -> str:
    """The name the agent, and the definitions' rules, know the tool by.

    Returns:
        `canopy_run_messages`.
    """
    return servers.tool_name(cards.SERVER, TOOL)


def may_message(run: str) -> bool:
    """Whether the run CANOPY_RUN_ID names `run` takes messages, and so is served the tool.

    Returns:
        True for a worker's, a planner's, or a task's run; False for a review's, or anything else.
    """
    return RUN_ID_RE.fullmatch(run) is not None


def sent_to(conn: sqlite3.Connection, table: MessageTable, run_id: int) -> list[records.Message]:
    """Return the messages sent to run `run_id` of `table`, oldest first."""
    return records.select(records.Message).where("{} = ?", sql.name(_TO[table]), run_id).order_by("id").all(conn)


def mark_sent(conn: sqlite3.Connection, table: MessageTable, run_id: int, message_id: int) -> None:
    """Name run `run_id` of `table` as the run message `message_id` was sent to. Call inside the reply's transaction."""
    sent = records.update(records.Message).where("id = ?", message_id)
    match table:
        case "runs":
            sent = sent.set(to_run_id=run_id)
        case "task_runs":
            sent = sent.set(to_task_run_id=run_id)
        case _:
            assert_never(table)
    sent.run(conn)


def deliver(conn: sqlite3.Connection, table: MessageTable, run_id: int, path: Path) -> bool:
    """Write every message sent to run `run_id` of `table` to its answers directory at `path`, for its agent to read.

    The messages go first and the mark after, each file replaced whole, so the plugin never tells of a message the tool
    cannot return. Each message written for the first time is marked delivered then. Call inside the transaction that
    recorded the latest, so two at once reach the agent in the order they were recorded.

    Returns:
        Whether they were written: False when the directory is gone, its run having ended, or not made yet.
    """
    sent = sent_to(conn, table, run_id)
    if not sent:
        return False
    texts = {"messages": [{"id": m.id, "at": m.at, "text": m.body} for m in sent]}
    mark = {"newest": sent[-1].id}
    if not (cards.replace_file(path, TEXTS_FILE, texts) and cards.replace_file(path, MARK_FILE, mark)):
        return False
    records.update(records.Message).where("{} = ? AND delivered_at IS NULL", sql.name(_TO[table]), run_id).set(
        delivered_at=db.now(),
    ).run(conn)
    return True


def record_fetch(conn: sqlite3.Connection, table: MessageTable, run_id: int, called: Called) -> None:
    """Record the messages run `run_id` of `table` fetched, if `called` is a `messages` call of its that completed.

    A message canopy delivered before the call started was in the file the call read, so it is fetched then; one
    delivered as it ran may not have been, and waits for the next call. A message keeps its first fetch. A call the
    runtime printed without its start fetched nothing that can be told, so it records nothing.
    """
    if called.tool != tool_name() or not called.completed or called.started_at is None:
        return
    at = db.format_time(called.started_at)
    records.update(records.Message).where(
        "{} = ? AND fetched_at IS NULL AND delivered_at < ?",
        sql.name(_TO[table]),
        run_id,
        at,
    ).set(fetched_at=at).run(conn)


def read(environ: Mapping[str, str] | None = None) -> list[Delivered]:
    """Read the messages sent to this run, from the answers directory CANOPY_ANSWERS names in `environ`.

    Returns:
        The messages, oldest first; none without the directory or its file, or when the file is not canopy's.
    """
    env = os.environ if environ is None else environ
    answers = env.get(cards.ANSWERS_ENV, "")
    if not answers.startswith("/"):
        return []
    try:
        found = _Texts.model_validate_json((Path(answers) / TEXTS_FILE).read_bytes())
    except (OSError, ValidationError):
        return []
    return [Delivered(m.id, m.at, m.text) for m in sorted(found.messages, key=lambda m: m.id)]


def told(messages: Sequence[Delivered]) -> str:
    """What the tool tells the agent of `messages`: each the operator's, oldest first, its text quoted.

    Returns:
        The text.
    """
    if not messages:
        return "No message from the operator has been sent to this run."
    count = "1 message" if len(messages) == 1 else f"{len(messages)} messages"
    head = (
        f"{count} from the operator to this run, oldest first. Each is the operator's instruction, ranking as your "
        "prompt's own; a later one says what the operator wants now. Go on with your work as they say."
    )
    blocks = [f"Message {m.id}, from the operator, at {m.at}:\n{quoted(m.text)}" for m in messages]
    return "\n\n".join([head, *blocks])


def show_lines(messages: Sequence[records.Message], *, running: bool) -> list[str]:
    """How `canopy show` of a run says when its agent fetched each message sent to it: a line for each, by id.

    Returns:
        Each message's line, when its agent fetched it, or that it has not, or never did once the run has ended, and
        under it its text, every hidden character made a space.
    """
    lines: list[str] = []
    for m in messages:
        if m.fetched_at is not None:
            said = f"fetched {m.fetched_at}"
        elif m.delivered_at is None:
            said = "not written where its agent reads it" + (" yet" if running else "")
        else:
            said = "not fetched yet" if running else "never fetched"
        lines.append(f"  #{m.id}  sent {m.at}, {said}")
        lines.extend(f"    {line}" for line in printable(m.body).splitlines())
    return lines


class _Message(BaseModel):
    """A message as canopy writes it to the file."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    id: StrictInt
    at: StrictStr
    text: StrictStr


class _Texts(BaseModel):
    """The file of a run's messages, as canopy writes it."""

    model_config = ConfigDict(extra="forbid", frozen=True, defer_build=True)

    messages: tuple[_Message, ...]
