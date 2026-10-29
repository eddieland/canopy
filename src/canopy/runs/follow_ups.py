"""Follow-up tickets (DESIGN §18): what a worker reports it filed, checked and recorded, and put to the operator.

An `implement` or `resume` worker on a ticket that is not itself a follow-up, public or private, may file tickets
outside its own and name them in its result line's `created` field, each with the repository it is for or null. `_run`
checks each entry alone, on its text, since the harness reads no tracker (D003), and records the ones that pass with the
run; a refused entry is named in the run's note and stored with its result, and raises `follow_up_unrecorded`
(`unrecorded`) until the run's ticket is done or forgotten. A recorded follow-up authorizes nothing: the run's close
tells the sinks once (`follow_ups.filed`, DESIGN §20); a label or the operator's start authorizes it, as any ticket.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, ConfigDict

from canopy.core import contract, conversation, db, records, sql

if TYPE_CHECKING:
    from collections.abc import Iterable

#: Where a run's stored result keeps the entries `_run` refused: the valid keys, and how many were not valid keys.
STORED = "follow_ups_unrecorded"
#: The attention item a refused entry raises, about the run's ticket (DESIGN §14).
REASON = "follow_up_unrecorded"
#: How many refused keys a note or an item names; the rest are counted.
MAX_NAMED = 20
#: How long an attention item's detail may be.
MAX_DETAIL = 2000


class _Reported(BaseModel):
    """The result line's `created` field, read apart from the rest of the result as memory's fields are (DESIGN §28).

    Untrusted, so each entry is checked in `check`: a value of any shape is read here, and one that is not an object of
    keys to repositories or nulls is refused there, never taken as the whole result being invalid.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, defer_build=True)

    created: object = None


@dataclass(frozen=True)
class Refusal:
    """An entry `_run` did not record: its key if it was a valid one, and why, in the harness's words."""

    key: str | None
    why: str


@dataclass(frozen=True)
class Checked:
    """A run's `created` field, checked: the entries to record, each with its repository, and those refused."""

    recorded: Mapping[str, str | None] = field(default_factory=dict)
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
        return f"follow-ups not recorded, so each is an ordinary ticket: {'; '.join(parts)}"

    def stored(self) -> dict[str, object]:
        """What the run's stored result keeps of the refused entries, for `follow_up_unrecorded`.

        Returns:
            Under `STORED`, the valid keys refused, at most `MAX_NAMED`, and how many others there were; {} when none
            was refused.
        """
        if not self.refused:
            return {}
        keys = [r.key for r in self.refused if r.key is not None][:MAX_NAMED]
        return {STORED: {"keys": keys, "others": len(self.refused) - len(keys)}}

    def refusing(self, why: str) -> Checked:
        """This check with every entry it would record refused instead, saying `why`.

        Returns:
            A check that records nothing.
        """
        return Checked(refused=[*self.refused, *(Refusal(key, why) for key in self.recorded)])


def parse(text: str) -> object:
    """Read the `created` field of `text`'s result line, the last line that starts with `{` (DESIGN §13).

    Returns:
        The field's value as JSON gave it, or None when there is no such field or no valid result line.
    """
    found = contract.last_line(_Reported, text)
    return found.created if found is not None else None


def check(
    conn: sqlite3.Connection,
    created: object,
    *,
    parent: str,
    repos: Collection[str],
    limit: int,
) -> Checked:
    """Check each entry of a run's `created` field alone, and return those to record and those refused (DESIGN §18).

    An entry is recorded when its key is a valid ticket key, not `parent`, new to the journal, and, where both keys
    have a prefix before their last `-`, in `parent`'s; its repository is one of `repos`, the workspace's, or null; and
    it is among the first `limit` that pass. A run whose ticket is itself a follow-up records none.

    Returns:
        The entries to record and the ones refused, each in the result's order.
    """
    if created is None:
        return Checked()
    if not isinstance(created, dict):
        return Checked(refused=[Refusal(None, "`created` is not an object of ticket keys")])
    entries = cast("dict[str, object]", created)
    run_wide = _run_wide(conn, parent, limit=limit)
    recorded: dict[str, str | None] = {}
    refused: list[Refusal] = []
    for key, repo in entries.items():
        if not valid_key(key):
            refused.append(Refusal(None, "not a ticket key"))
            continue
        # Past the bound, an entry is refused unread: a steered worker's long list costs no query each.
        past = f"past policy.max_follow_ups, {limit} from one run" if len(recorded) >= limit else ""
        why = run_wide or past or _check_entry(conn, key, repo, parent=parent, repos=repos)
        if why:
            refused.append(Refusal(key, why))
        else:
            recorded[key] = cast("str | None", repo)
    return Checked(recorded, refused)


def record(conn: sqlite3.Connection, checked: Checked, *, parent: str, run_id: int) -> list[str]:
    """Record the entries `check` passed, inside the transaction that closes run `run_id` (DESIGN §8 step 7).

    A key the journal came to know after the check, because another run reported it first, is not recorded: it is named
    in the run's note and stored result as any refused entry is.

    Returns:
        The keys recorded.
    """
    late: list[str] = []
    done: list[str] = []
    for key, repo in checked.recorded.items():
        (done if record_follow_up(conn, key, parent, run_id, repo) else late).append(key)
    if late:
        _note_late(conn, run_id, late)
    return done


@dataclass(frozen=True)
class Item:
    """The attention item the harness raises about follow-ups a run reported and the journal did not record."""

    ticket_key: str
    reason: str
    detail: str


def unrecorded(conn: sqlite3.Connection) -> list[Item]:
    """Return a `follow_up_unrecorded` item for each ticket not done whose `created` field a run refused (§14, §18).

    Only runs since the ticket's last forget count. Its cause is gone when the ticket is marked done or forgotten.
    The detail names each such run and each refused key, and counts the entries that were not valid keys.

    Returns:
        One item per ticket, by key.
    """
    refused = (
        sql.select("r.id, r.ticket_key, r.result_json")
        .from_("runs r")
        .join("tickets t ON t.key = r.ticket_key")
        .where("t.done = 0")
        .where("r.id > coalesce(t.forgotten_run_id, 0)")
        .where("json_valid(r.result_json)")
        .where("json_type(r.result_json, ?) = 'object'", f"$.{STORED}")
        .order_by("r.ticket_key, r.id")
    )
    rows = sql.execute(conn, refused).fetchall()
    by_ticket: dict[str, list[str]] = {}
    for row in rows:
        stored = contract.stored_object(row["result_json"]).get(STORED)
        said = _said(cast("Mapping[str, object]", stored)) if isinstance(stored, dict) else ""
        if said:
            by_ticket.setdefault(str(row["ticket_key"]), []).append(f"run:{row['id']} reported {said}")
    return [
        Item(
            key,
            REASON,
            (
                f"{'; '.join(runs)}, which canopy did not record as follow-ups: each is an ordinary ticket, worked "
                "only with a queue label, which starts one; the runs' notes say why"
            )[:MAX_DETAIL],
        )
        for key, runs in sorted(by_ticket.items())
    ]


def known_ticket(conn: sqlite3.Connection, key: str) -> bool:
    """Whether the journal knows `key` as a ticket: a `tickets` row, a run, a follow-up record, or an old split's child.

    Returns:
        True if any of them names `key`.
    """
    names = sql.union(
        sql.select("1").from_("tickets").where("key = ?", key),
        sql.select("1").from_("runs").where("ticket_key = ?", key),
        sql.select("1").from_("follow_ups").where("key = ?", key),
        sql.select("1").from_("split_children").where("child_key = ?", key),
        every=True,
    )
    # The LIMIT is the compound's, so it is written whole.
    return sql.execute(conn, sql.frag("{} LIMIT 1", names)).fetchone() is not None


def record_follow_up(conn: sqlite3.Connection, key: str, parent: str, run_id: int, repo: str | None) -> bool:
    """Record `key` as a follow-up of `parent` that run `run_id` reported, inside the caller's transaction.

    Returns:
        True if it was recorded; False when the journal already knows `key`, which nothing then changes.
    """
    if known_ticket(conn, key):
        return False
    records.insert(records.FollowUp, key=key, parent_key=parent, run_id=run_id, repo=repo, at=db.now()).run(conn)
    return True


def get_follow_up(conn: sqlite3.Connection, key: str) -> records.FollowUp | None:
    """Return `key`'s follow-up record, or None if no run reported it."""
    return records.select(records.FollowUp).where("key = ?", key).one(conn)


def valid_key(key: object) -> bool:
    """Whether `key`, as a result line gave it, is a ticket key canopy can record: its text alone (D003).

    Returns:
        True for a string of at most `conversation.MAX_KEY` characters that `conversation.KEY_RE` matches.
    """
    return isinstance(key, str) and len(key) <= conversation.MAX_KEY and conversation.KEY_RE.fullmatch(key) is not None


def project_of(key: str) -> str:
    """Return `key`'s project, as far as its shape shows it: what comes before its last `-`, or "" when it has none."""
    return key.rpartition("-")[0]


def _run_wide(conn: sqlite3.Connection, parent: str, *, limit: int) -> str:
    # Why a run records no follow-up at all, or "" when it may record some.
    if get_follow_up(conn, parent) is not None:
        return f"{parent} is itself a follow-up, and a follow-up's runs file none"
    if limit == 0:
        return "policy.max_follow_ups is 0"
    return ""


def _check_entry(conn: sqlite3.Connection, key: str, repo: object, *, parent: str, repos: Collection[str]) -> str:
    # Why one entry cannot be recorded, or "" when it can, as far as the entry alone shows it.
    if key == parent:
        return "the run's own ticket"
    if project_of(key) and project_of(parent) and project_of(key) != project_of(parent):
        return f"not in {parent}'s project"
    if repo is not None and (not isinstance(repo, str) or repo not in repos):
        return "its repository is not one in this workspace"
    if known_ticket(conn, key):
        return "not a new ticket: the journal already knows it"
    return ""


def _note_late(conn: sqlite3.Connection, run_id: int, late: Iterable[str]) -> None:
    # Name the keys another run recorded first in run `run_id`'s note and stored refusals, as `check` names its own.
    row = sql.execute(conn, sql.select("result_json").from_("runs").where("id = ?", run_id)).fetchone()
    result = contract.stored_object(row[0] if row is not None else None)
    keys = list(late)
    added = "; ".join(f"{key}: another run recorded it first" for key in keys)
    note = str(result.get("harness") or "")
    result["harness"] = f"{note}; follow-ups not recorded: {added}" if note else f"follow-ups not recorded: {added}"
    stored = result.get(STORED)
    held: Mapping[str, object] = cast("dict[str, object]", stored) if isinstance(stored, dict) else {}
    found = held.get("keys")
    named: list[str] = [k for k in cast("list[object]", found) if isinstance(k, str)] if isinstance(found, list) else []
    room = max(MAX_NAMED - len(named), 0)
    others = held.get("others")
    result[STORED] = {
        "keys": [*named, *keys[:room]],
        "others": (others if isinstance(others, int) else 0) + len(keys[room:]),
    }
    records.update(records.Run).set(result_json=json.dumps(result)).where("id = ?", run_id).run(conn)


def _said(stored: Mapping[str, object]) -> str:
    # What one run's stored refusals name: its valid keys, then a count of the rest. Untrusted, so read with care.
    keys = stored.get("keys")
    others = stored.get("others")
    named = [str(k) for k in cast("list[object]", keys) if valid_key(k)] if isinstance(keys, list) else []
    count = others if isinstance(others, int) and others > 0 else 0
    parts = [*named]
    if count:
        parts.append(f"{count} other {'entry' if count == 1 else 'entries'}")
    return ", ".join(parts)
