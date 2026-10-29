"""The tickets a one-off task's run reports it filed (DESIGN §36): checked on their text, and recorded against the task.

A task whose submission names a tracker project may file tickets there, with no queue label, at most
`policy.max_follow_ups` per run, and names them in its result line's `created`, a list of keys. `_task` checks each
entry alone, on its text, since the harness reads no tracker (D003): a ticket key, in the project as far as its shape
shows (`follow_ups.project_of`), and among the first `limit` that pass. Those are recorded against the task, in
`task_tickets`, never as a ticket of canopy's: no `tickets`, `follow_ups`, or `runs` row names one, and none is worked
until the operator labels or starts it. A refused entry, and any entry from a task that names no project, is named in
the run's note and stored with its result, and raises `task_ticket_unrecorded` until the operator replies to the task
or stops it, so a steered worker's ticket elsewhere is not silent.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from canopy.core import contract, conversation, db, records, sql
from canopy.runs import follow_ups
from canopy.runs.follow_ups import Refusal

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterable, Mapping

#: Where a task run's stored result keeps the entries `_task` refused: the valid keys, and how many others there were.
STORED = "tickets_unrecorded"
#: The attention item a refused entry raises, about the task (DESIGN §14, §36).
REASON = "task_ticket_unrecorded"
#: How many refused keys a note or a stored result names; the rest are counted.
MAX_NAMED = follow_ups.MAX_NAMED


@dataclass(frozen=True)
class Checked:
    """A task run's `created` field, checked: the keys to record against the task, in order, and the entries refused."""

    recorded: Sequence[str] = ()
    refused: Sequence[Refusal] = ()

    def note(self) -> str:
        """The run's harness note about what was refused, or "" when nothing was.

        Returns:
            A sentence naming each refused key with why, at most `MAX_NAMED` of them, and counting the rest.
        """
        if not self.refused:
            return ""
        named = [r for r in self.refused if r.key is not None]
        parts = [f"{r.key}: {r.why}" for r in named[:MAX_NAMED]]
        rest = len(self.refused) - len(parts)
        if rest:
            parts.append(f"{rest} more {'entry' if rest == 1 else 'entries'}, not named")
        return f"tickets not recorded against the task: {'; '.join(parts)}"

    def stored(self) -> dict[str, object]:
        """What the run's stored result keeps of the refused entries, for `task_ticket_unrecorded`.

        Returns:
            Under `STORED`, the valid keys refused, at most `MAX_NAMED`, and how many others there were; {} when none
            was refused.
        """
        if not self.refused:
            return {}
        keys = [r.key for r in self.refused if r.key is not None][:MAX_NAMED]
        return {STORED: {"keys": keys, "others": len(self.refused) - len(keys)}}


def check(created: object, *, project: str | None, limit: int) -> Checked:
    """Check each entry of a task run's `created` field alone, and return the keys to record and those refused (§36).

    An entry is recorded when it is a ticket key, its project, where its shape shows one, is `project`, and it is among
    the first `limit` that pass; a key the field repeats is recorded once. A task whose submission named no project
    records none.

    Returns:
        The keys to record and the entries refused, each in the result's order.
    """
    if created is None:
        return Checked()
    if not isinstance(created, list):
        return Checked(refused=[Refusal(None, "`created` is not a list of ticket keys")])
    recorded: list[str] = []
    refused: list[Refusal] = []
    for key in cast("list[object]", created):
        if not follow_ups.valid_key(key):
            refused.append(Refusal(None, "not a ticket key"))
            continue
        key = cast("str", key)
        if key in recorded:
            continue
        why = _why(key, project=project, limit=limit, recorded=len(recorded))
        if why:
            refused.append(Refusal(key, why))
        else:
            recorded.append(key)
    return Checked(recorded, refused)


def record(conn: sqlite3.Connection, task_id: int, run_id: int, keys: Iterable[str]) -> list[str]:
    """Record `keys` against task `task_id`, as run `run_id` reported them, inside the transaction that closes it.

    A key an earlier run of the task already recorded keeps its first row.

    Returns:
        The keys this run recorded, in order.
    """
    done: list[str] = []
    for key in keys:
        insert = records.insert(
            records.TaskTicket,
            task_id=task_id,
            task_run_id=run_id,
            key=key,
            at=db.now(),
        ).or_ignore()
        if insert.run(conn).rowcount == 1:
            done.append(key)
    return done


def of_task(conn: sqlite3.Connection, task_id: int) -> list[records.TaskTicket]:
    """Return the tickets recorded against task `task_id`, in the order its runs reported them."""
    query = records.select(records.TaskTicket).where("task_id = ?", task_id).order_by("id")
    return query.all(conn)


@dataclass(frozen=True)
class Unrecorded:
    """A task run that reported tickets canopy did not record, and that the operator has not had a word on since."""

    task_id: int
    run_id: int
    #: How many entries it refused, named or not.
    count: int
    #: When the run ended.
    at: str


def unrecorded(conn: sqlite3.Connection) -> list[Unrecorded]:
    """Return each task run whose refused entries raise `task_ticket_unrecorded` now, by task (DESIGN §14, §36).

    A run's refusals raise it while its task is not stopped and no reply of the operator's to the task is newer than
    the run's own messages: their reply or their stop is their word on the task after reading it.

    Returns:
        The runs, by task and run.
    """
    replied = sql.frag(
        "EXISTS (SELECT 1 FROM messages o WHERE o.subject_kind = ? AND o.subject_id = CAST(r.task_id AS TEXT)"
        " AND o.source = 'operator' AND o.id > coalesce((SELECT max(m.id) FROM messages m WHERE m.task_run_id = r.id),"
        " 0))",
        conversation.TASK,
    )
    query = (
        records.select(records.TaskRun, "r")
        .join("tasks t ON t.id = r.task_id")
        .where("t.stopped_at IS NULL AND r.status != 'running'")
        .where("json_valid(r.result_json)")
        .where("json_type(r.result_json, ?) = 'object'", f"$.{STORED}")
        .where("NOT {}", replied)
        .order_by("r.task_id, r.id")
    )
    found: list[Unrecorded] = []
    for run in query.all(conn):
        stored = contract.stored_object(run.result_json).get(STORED)
        count = _count(cast("Mapping[str, object]", stored)) if isinstance(stored, dict) else 0
        if count:
            found.append(Unrecorded(run.task_id, run.id, count, run.ended_at or run.started_at))
    return found


def _why(key: str, *, project: str | None, limit: int, recorded: int) -> str:
    # Why one entry cannot be recorded, or "" when it can, as far as the entry alone shows it.
    if project is None:
        return "the task names no project, so it files no tickets"
    if limit == 0:
        return "policy.max_follow_ups is 0"
    if recorded >= limit:
        return f"past policy.max_follow_ups, {limit} from one run"
    own = follow_ups.project_of(key)
    if own and own != project:
        return f"not in the task's project, {project}"
    return ""


def _count(stored: Mapping[str, object]) -> int:
    # How many entries one run's stored refusals count: its valid keys and the others. Untrusted, so read with care.
    keys = stored.get("keys")
    others = stored.get("others")
    named = len([k for k in cast("list[object]", keys) if follow_ups.valid_key(k)]) if isinstance(keys, list) else 0
    return named + (others if isinstance(others, int) and others > 0 else 0)
