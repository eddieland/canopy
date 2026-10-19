"""Follow-up tickets (DESIGN §18): what a worker reports it filed, checked and recorded, and put to the operator.

An `implement` or `resume` worker on a ticket that is not itself a follow-up, public or private, may file tickets
outside its own and name them in its result line's `created` field, each with the repository it is for or null. `_run`
checks each entry alone, on its text, since the harness reads no tracker (D003), and records the ones that pass with the
run; a refused entry is named in the run's note and stored with its result, and raises `follow_up_unrecorded`
(`unrecorded`) until the run's ticket is done or forgotten. A recorded follow-up authorizes nothing: canopy raises
`follow_up_filed` about its parent (`filed`) until the operator labels or starts it, as any ticket is authorized.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, ConfigDict

from canopy.core import contract, conversation, db

if TYPE_CHECKING:
    from collections.abc import Iterable

#: Where a run's stored result keeps the entries `_run` refused: the valid keys, and how many were not valid keys.
STORED = "follow_ups_unrecorded"
#: The attention item a refused entry raises, about the run's ticket (DESIGN §14).
REASON = "follow_up_unrecorded"
#: The attention item a recorded follow-up raises, about its parent, until the operator labels or starts it (§14).
FILED = "follow_up_filed"
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
        if not _valid_key(key):
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
        (done if db.record_follow_up(conn, key, parent, run_id, repo) else late).append(key)
    if late:
        _note_late(conn, run_id, late)
    return done


@dataclass(frozen=True)
class Item:
    """An attention item the harness raises about follow-ups, about one ticket: `FILED` or `REASON`."""

    ticket_key: str
    reason: str
    detail: str


def items(conn: sqlite3.Connection) -> list[Item]:
    """Return the attention items about follow-ups the harness raises every tick (DESIGN §14, §18).

    Returns:
        Each `follow_up_filed` item (`filed`), then each `follow_up_unrecorded` one (`unrecorded`).
    """
    return [*filed(conn), *unrecorded(conn)]


def filed(conn: sqlite3.Connection) -> list[Item]:
    """Return a `follow_up_filed` item for each ticket not done whose runs filed follow-ups not yet decided on.

    A follow-up authorizes nothing: it waits until a human does what authorizes any ticket (DESIGN §18). It stops
    waiting once canopy has a run of it, which only a queue label or the operator's start lets the overseer dispatch;
    once the operator started it; or once it is marked done. Attention items have no dismissal (§14), so one the
    operator does not want stops being asked about when its parent is done or forgotten: only follow-ups recorded since
    the parent's latest forget count.

    Returns:
        One item per parent, by key, naming each waiting follow-up with its repository and the run that filed it.
    """
    rows = conn.execute(
        "SELECT f.key, f.parent_key, f.repo, f.run_id FROM follow_ups f JOIN tickets p ON p.key = f.parent_key "
        "LEFT JOIN tickets t ON t.key = f.key "
        "WHERE p.done = 0 AND (p.forgotten_at IS NULL OR f.at > p.forgotten_at) AND coalesce(t.done, 0) = 0 "
        "AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.ticket_key = f.key) "
        "AND NOT EXISTS (SELECT 1 FROM starts s WHERE s.subject_kind = ? AND s.subject_id = f.key) "
        "ORDER BY f.parent_key, f.at, f.key",
        (conversation.TICKET,),
    ).fetchall()
    by_parent: dict[str, list[str]] = {}
    for row in rows:
        repo = f"for {row['repo']}" if row["repo"] is not None else "for no repository named"
        by_parent.setdefault(str(row["parent_key"]), []).append(f"{row['key']} ({repo}, run:{row['run_id']})")
    return [
        Item(
            parent,
            FILED,
            (
                f"its workers filed {', '.join(waiting)}; canopy works none of them until you add a queue label to it, "
                "or start it privately with `canopy start KEY`"
            )[:MAX_DETAIL],
        )
        for parent, waiting in sorted(by_parent.items())
    ]


def unrecorded(conn: sqlite3.Connection) -> list[Item]:
    """Return a `follow_up_unrecorded` item for each ticket not done whose `created` field a run refused (§14, §18).

    Only runs since the ticket's last forget count. Its cause is gone when the ticket is marked done or forgotten.
    The detail names each such run and each refused key, and counts the entries that were not valid keys.

    Returns:
        One item per ticket, by key.
    """
    rows = conn.execute(
        "SELECT r.id, r.ticket_key, r.result_json FROM runs r JOIN tickets t ON t.key = r.ticket_key "
        "WHERE t.done = 0 AND r.id > coalesce(t.forgotten_run_id, 0) AND json_valid(r.result_json) "
        "AND json_type(r.result_json, ?) = 'object' ORDER BY r.ticket_key, r.id",
        (f"$.{STORED}",),
    ).fetchall()
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


def _run_wide(conn: sqlite3.Connection, parent: str, *, limit: int) -> str:
    # Why a run records no follow-up at all, or "" when it may record some.
    if db.get_follow_up(conn, parent) is not None:
        return f"{parent} is itself a follow-up, and a follow-up's runs file none"
    if limit == 0:
        return "policy.max_follow_ups is 0"
    return ""


def _check_entry(conn: sqlite3.Connection, key: str, repo: object, *, parent: str, repos: Collection[str]) -> str:
    # Why one entry cannot be recorded, or "" when it can, as far as the entry alone shows it.
    if key == parent:
        return "the run's own ticket"
    if _prefix(key) and _prefix(parent) and _prefix(key) != _prefix(parent):
        return f"not in {parent}'s project"
    if repo is not None and (not isinstance(repo, str) or repo not in repos):
        return "its repository is not one in this workspace"
    if db.known_ticket(conn, key):
        return "not a new ticket: the journal already knows it"
    return ""


def _valid_key(key: object) -> bool:
    return isinstance(key, str) and len(key) <= conversation.MAX_KEY and conversation.KEY_RE.fullmatch(key) is not None


def _prefix(key: str) -> str:
    # A key's project, as far as its shape shows it: what comes before its last `-`, or "" when it has none.
    return key.rpartition("-")[0]


def _note_late(conn: sqlite3.Connection, run_id: int, late: Iterable[str]) -> None:
    # Name the keys another run recorded first in run `run_id`'s note and stored refusals, as `check` names its own.
    row = conn.execute("SELECT result_json FROM runs WHERE id = ?", (run_id,)).fetchone()
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
    conn.execute("UPDATE runs SET result_json = ? WHERE id = ?", (json.dumps(result), run_id))


def _said(stored: Mapping[str, object]) -> str:
    # What one run's stored refusals name: its valid keys, then a count of the rest. Untrusted, so read with care.
    keys = stored.get("keys")
    others = stored.get("others")
    named = [str(k) for k in cast("list[object]", keys) if _valid_key(k)] if isinstance(keys, list) else []
    count = others if isinstance(others, int) and others > 0 else 0
    parts = [*named]
    if count:
        parts.append(f"{count} other {'entry' if count == 1 else 'entries'}")
    return ", ".join(parts)
